"""Anthropic provider — wraps the existing Claude API path.

The system prompt is marked cacheable (ephemeral). Sonnet's minimum
cacheable prefix is 2048 tokens — until the assembled workspace prompt
crosses that threshold the marker is a no-op. Once Tier 2 memory grows
the cache activates automatically. We log usage every call so cache
behavior is visible.
"""

from __future__ import annotations

import logging
import os

import anthropic

from app import config

from .base import LLMProvider, ProviderError

log = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        self._client: anthropic.AsyncAnthropic | None = None

    def _resolved_api_key(self) -> str | None:
        provider = config.get().models.providers.get("anthropic")
        if provider is not None:
            v = provider.api_key
            if v:
                return v
        # Fallback so unconfigured installs (no providers.anthropic block)
        # still pick up an env var the SDK would have read anyway.
        return os.getenv("ANTHROPIC_API_KEY") or None

    def _resolved_base_url(self) -> str | None:
        provider = config.get().models.providers.get("anthropic")
        if provider is not None and provider.base_url:
            return provider.base_url
        return os.getenv("ANTHROPIC_BASE_URL") or None

    def is_available(self) -> bool:
        return bool(self._resolved_api_key())

    def _client_singleton(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            api_key = self._resolved_api_key()
            base_url = self._resolved_base_url()
            kwargs: dict[str, str] = {}
            if api_key:
                kwargs["api_key"] = api_key
            if base_url:
                kwargs["base_url"] = base_url
                log.info("anthropic client: base_url=%s", base_url)
            self._client = anthropic.AsyncAnthropic(**kwargs)
        return self._client

    async def generate_reply(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1024,
    ) -> str:
        if not self.is_available():
            raise ProviderError("Anthropic API key not configured")

        client = self._client_singleton()
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "disabled"},
            output_config={"effort": "low"},
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_message}],
        )

        usage = response.usage
        log.info(
            "anthropic reply: model=%s in=%s out=%s cache_read=%s cache_write=%s stop=%s",
            model,
            usage.input_tokens, usage.output_tokens,
            getattr(usage, "cache_read_input_tokens", 0),
            getattr(usage, "cache_creation_input_tokens", 0),
            response.stop_reason,
        )

        text_parts: list[str] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
        return "".join(text_parts).strip()
