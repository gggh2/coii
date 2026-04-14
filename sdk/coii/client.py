"""Coii SDK client."""
import time
import threading
import uuid
from typing import Optional
import contextvars
import httpx

from .context import CoiiContext

# Context variables for async-safe trace tracking
_current_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "coii_trace_id", default=None
)
_current_variant: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "coii_variant", default=None
)


class Coii:
    """Coii SDK client.

    Usage::

        coii = Coii(host="http://localhost:8080")
        client = openai.OpenAI()
        coii.instrument(client)

        ctx = coii.start(user_id)
        response = client.chat.completions.create(model=ctx.model, ...)
        coii.outcome(user_id, "ticket_resolved")
    """

    def __init__(
        self,
        host: str = "http://localhost:8080",
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
    ):
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._default_model = default_model
        self._http = httpx.Client(
            base_url=f"{self._host}/api/v1",
            timeout=5.0,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
        self._async_http = httpx.AsyncClient(
            base_url=f"{self._host}/api/v1",
            timeout=5.0,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
        self._bg_executor = threading.Thread(target=self._noop, daemon=True)

    def _noop(self):
        pass

    def _send_async(self, method: str, path: str, body: dict):
        """Fire-and-forget background HTTP request."""
        def _do():
            try:
                self._http.request(method, path, json=body)
            except Exception:
                pass  # Non-blocking — never raise

        t = threading.Thread(target=_do, daemon=True)
        t.start()

    def _send_sync(self, method: str, path: str, **kwargs):
        """Synchronous HTTP request."""
        try:
            resp = self._http.request(method, path, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return None

    def instrument(self, client) -> None:
        """Patch an LLM SDK client to automatically track calls.

        Supports OpenAI Python SDK and Anthropic Python SDK.
        """
        if hasattr(client, "chat") and hasattr(client.chat, "completions"):
            self._patch_openai(client)
        elif hasattr(client, "messages") and hasattr(client.messages, "create"):
            self._patch_anthropic(client)
        else:
            raise ValueError(
                "Unrecognized client type. Coii supports OpenAI and Anthropic SDKs. "
                "For other SDKs, use ctx.log_span() to record manually."
            )

    def start(self, user_id: str, session_id: Optional[str] = None) -> CoiiContext:
        """Start a user interaction: creates a trace and gets experiment assignments."""
        trace_id = f"tr_{uuid.uuid4().hex[:20]}"

        # Create trace (async, non-blocking)
        self._send_async("POST", "/traces", {
            "id": trace_id,
            "user_id": user_id,
            "session_id": session_id,
        })

        # Get assignments (sync — we need the variant before user code continues)
        assignments = {}
        try:
            data = self._send_sync("GET", f"/assignments?user_id={user_id}")
            if data:
                assignments = data
        except Exception:
            pass

        # Set contextvars for instrument hooks
        _current_trace_id.set(trace_id)
        primary_variant = None
        if assignments:
            first = next(iter(assignments.values()), None)
            if first:
                primary_variant = first.get("variant")
        _current_variant.set(primary_variant)

        return CoiiContext(self, user_id, trace_id, assignments)

    def outcome(self, user_id: str, event: str, properties: Optional[dict] = None) -> None:
        """Record a business outcome. Non-blocking."""
        self._send_async("POST", "/outcomes", {
            "user_id": user_id,
            "event_name": event,
            "properties": properties or {},
        })

    def _end_trace(self, trace_id: str) -> None:
        """Mark a trace as ended. Non-blocking."""
        self._send_async("PATCH", f"/traces/{trace_id}/end", {})

    def _patch_openai(self, client) -> None:
        """Monkey-patch OpenAI SDK to track LLM calls."""
        original = client.chat.completions.create
        coii_ref = self

        def patched(*args, **kwargs):
            trace_id = _current_trace_id.get()
            start = time.monotonic()
            response = original(*args, **kwargs)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            if trace_id:
                model = kwargs.get("model") or (args[0] if args else "unknown")
                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
                output_tokens = getattr(usage, "completion_tokens", None) if usage else None
                coii_ref._send_async("POST", "/spans", {
                    "trace_id": trace_id,
                    "type": "llm",
                    "model": model,
                    "latency_ms": elapsed_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                })
            return response

        client.chat.completions.create = patched

    def _patch_anthropic(self, client) -> None:
        """Monkey-patch Anthropic SDK to track LLM calls."""
        original = client.messages.create
        coii_ref = self

        def patched(*args, **kwargs):
            trace_id = _current_trace_id.get()
            start = time.monotonic()
            response = original(*args, **kwargs)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            if trace_id:
                model = kwargs.get("model", "unknown")
                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "input_tokens", None) if usage else None
                output_tokens = getattr(usage, "output_tokens", None) if usage else None
                coii_ref._send_async("POST", "/spans", {
                    "trace_id": trace_id,
                    "type": "llm",
                    "model": model,
                    "latency_ms": elapsed_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                })
            return response

        client.messages.create = patched

    def close(self):
        self._http.close()
