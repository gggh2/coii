"""End-to-end orchestration for a Linear webhook delivery.

Pipeline (PRD §10):
  raw body -> LinearAdapter.parse_webhook -> TicketEvent
            -> matcher.match(event, triggers) -> [Trigger]
            -> for each: load_agent + assemble prompt
            -> log prompt + post confirmation comment to ticket

Returns a Result. The controller logs Err but always returns 200 to Linear so
it doesn't retry on our internal failures.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app import config
from app.result import Err, Ok, Result
from app.runtimes import claude_code, llm
from app.agents.loader import AgentContext, load_agent
from app.trackers.linear import LinearAdapter
from app.trackers.types import Comment, TicketEvent
from app.triggers.loader import load_triggers
from app.triggers.matcher import match
from app.triggers.types import Trigger
from app.util import coii_root
import os

log = logging.getLogger(__name__)

# Module-level singletons. Triggers reload on every event so editing
# any *_workflow.yaml file takes effect without restarting. (Files are small.)
_linear_adapter: LinearAdapter | None = None


def get_linear_adapter() -> LinearAdapter:
    """Construct (once) a LinearAdapter using credentials resolved from Config.

    The adapter still accepts plain ``api_key`` / ``webhook_secret`` strings,
    but here we resolve them through the config layer so any SecretRef shape
    (env / file / exec) works uniformly.
    """
    global _linear_adapter
    if _linear_adapter is None:
        linear = config.get().linear
        _linear_adapter = LinearAdapter(
            api_key=linear.api_key or None,
            webhook_secret=linear.webhook_secret or None,
        )
    return _linear_adapter


def _reset_linear_adapter() -> None:
    """Test hook: drop the adapter so the next call re-reads config."""
    global _linear_adapter
    _linear_adapter = None


async def handle_linear_event(
    raw_body: bytes, signature: str | None,
) -> Result[dict[str, Any]]:
    """Webhook entrypoint: parse the raw body, then delegate to dispatch_event."""
    adapter = get_linear_adapter()

    try:
        event = adapter.parse_webhook(raw_body, signature)
    except PermissionError as e:
        return Err("invalid_signature", str(e))
    except ValueError as e:
        return Err("malformed_payload", str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("unexpected error parsing webhook")
        return Err("parse_failed", repr(e))

    if event is None:
        return Ok({"matched": 0, "skipped": True})

    return await dispatch_event(adapter, event)


async def dispatch_event(
    adapter: LinearAdapter, event: TicketEvent,
) -> Result[dict[str, Any]]:
    """Match an already-parsed TicketEvent against triggers and fire matches.

    Shared by the webhook path (handle_linear_event) and the poller. Either
    source can produce a TicketEvent; everything from here on is identical.
    """
    # Linear's Comment + AgentSession payloads don't include the issue's labels
    # or status. Enrich via GraphQL so trigger matching has the full context.
    event = await _enrich_if_sparse(adapter, event)

    triggers = load_triggers()
    matched = match(event, triggers)
    log.info(
        "linear event ticket=%s type=%s status=%r project=%r assignee=%r labels=%s "
        "→ matched %d/%d trigger(s): %s",
        event.ticket.id, event.type, event.ticket.status, event.ticket.project,
        event.ticket.assignee, list(event.ticket.labels),
        len(matched), len(triggers),
        [t.name for t in matched],
    )

    if not matched:
        return Ok({"matched": 0, "event": event.type, "ticket": event.ticket.id})

    for trigger in matched:
        await _fire_trigger(adapter, event, trigger)

    return Ok({"matched": len(matched), "event": event.type, "ticket": event.ticket.id})


async def _enrich_if_sparse(
    adapter: LinearAdapter, event: TicketEvent,
) -> TicketEvent:
    """If labels and status are both empty, refetch the ticket via API.

    Linear's Comment + AgentSession webhook payloads strip these fields. Without
    them, label_contains / ticket_status triggers can never match. A single
    extra GraphQL call per sparse event is cheap and keeps trigger semantics
    consistent across event types.
    """
    t = event.ticket
    if t.labels or t.status:
        return event
    if not t.id:
        return event
    try:
        full = await adapter.get_ticket(t.id)
    except Exception as e:  # noqa: BLE001
        log.warning("failed to enrich ticket %s: %s — using sparse data", t.id, e)
        return event
    enriched = TicketEvent(
        tracker=event.tracker,
        type=event.type,
        ticket=full,
        actor=event.actor,
        raw=event.raw,
    )
    log.info(
        "enriched %s ticket=%s status=%r labels=%s",
        event.type, full.id, full.status, list(full.labels),
    )
    return enriched


# Tag the LLM appends to its reply to ask the backend to transition the ticket.
# Format: <status>In Progress</status> or <status>Blocked: out of memory</status>.
# Case-insensitive. Anything before the colon is the target Linear state name;
# everything after is rendered as a parenthetical reason in the comment body.
_STATUS_TAG = re.compile(r"<status>\s*([^<\n]+?)\s*</status>", re.IGNORECASE)


def _extract_status_directive(body: str) -> tuple[str | None, str | None, str]:
    """Pull a `<status>...</status>` directive out of an LLM reply.

    Returns (target_state, reason, cleaned_body).
    target_state is None if no tag was present.
    """
    m = _STATUS_TAG.search(body)
    if not m:
        return None, None, body
    raw = m.group(1).strip()
    if ":" in raw:
        state, reason = raw.split(":", 1)
        state = state.strip()
        reason = reason.strip() or None
    else:
        state = raw
        reason = None
    cleaned = _STATUS_TAG.sub("", body).strip()
    return state, reason, cleaned


async def _fire_trigger(
    adapter: LinearAdapter, event: TicketEvent, trigger: Trigger,
) -> None:
    """Load agent, generate an LLM-driven reply, optionally transition
    the Linear ticket per a `<status>` tag in the reply, then post.
    """
    try:
        ctx = load_agent(trigger.agent)
    except FileNotFoundError as e:
        log.error("trigger %r referenced missing agent %r: %s",
                  trigger.name, trigger.agent, e)
        return

    # Optional kanban behavior: if the trigger declares a `pre_status`, flip
    # the ticket into that state before invoking the runtime so the human sees
    # immediate "the bot picked it up" feedback.
    pre_status = (trigger.raw.get("pre_status") or "").strip() or None
    if pre_status and event.ticket.status != pre_status:
        try:
            await adapter.set_status(event.ticket.id, pre_status)
            log.info("pre-transitioned %s → %r per trigger config",
                     event.ticket.id, pre_status)
        except Exception as e:  # noqa: BLE001
            log.warning("pre_status %r transition failed for %s: %s",
                        pre_status, event.ticket.id, e)

    history = await _fetch_history(adapter, event.ticket.id)
    user_message = _user_message(event, trigger, history)
    runtime_cfg = ctx.config.runtime or {}
    runtime_type = runtime_cfg.get("type", "auto")
    # Optional per-agent override, e.g. "openai/gpt-4o". When unset,
    # the llm_direct runtime falls back to LLM_MODEL env / DEFAULT_SPEC.
    model_spec = runtime_cfg.get("model")

    try:
        body = await _generate_body(
            runtime_type, ctx.prompt, user_message, trigger, event,
            model_spec=model_spec,
        )
    except claude_code.AlreadyRunning as e:
        # Linear emits ticket.created + ticket.updated as separate webhooks
        # for the same logical create event. The first one acquired the
        # workspace lock; we skip silently rather than post a duplicate
        # comment or fall back to template.
        log.info("skipping trigger=%r for %s: %s",
                 trigger.name, event.ticket.id, e)
        return

    target_state, reason, body = _extract_status_directive(body)
    if target_state:
        try:
            await adapter.set_status(event.ticket.id, target_state)
            log.info("transitioned %s → %r (reason=%r)",
                     event.ticket.id, target_state, reason)
        except Exception as e:  # noqa: BLE001
            log.warning("status transition to %r failed for %s: %s",
                        target_state, event.ticket.id, e)
            body += (
                f"\n\n_(I tried to transition this ticket to "
                f"`{target_state}` but it failed: `{e}`. The state name may "
                "not exist in your workspace — check `/admin/linear/inspect`.)_"
            )

    try:
        await adapter.post_comment(event.ticket.id, body)
        log.info("posted reply to ticket %s (%d chars)", event.ticket.id, len(body))
    except Exception as e:  # noqa: BLE001
        log.exception("failed to post comment to %s: %s", event.ticket.id, e)


async def _generate_body(
    runtime_type: str, system_prompt: str, user_message: str,
    trigger: Trigger, event: TicketEvent,
    *, model_spec: str | None = None,
) -> str:
    """Pick a runtime per workspace.json and fall back to template on failure.

    runtime_type: "claude_code" | "llm_direct" | "auto" (prefer claude_code).
    model_spec: optional ``<provider>/<model-id>`` override for llm_direct.
    """
    async def _llm(sys: str, msg: str, ev: TicketEvent) -> str:
        return await _run_llm_direct(sys, msg, ev, model_spec=model_spec)

    candidates: list[tuple[str, callable]] = []
    if runtime_type == "claude_code":
        candidates.append(("claude_code", _run_claude_code))
    elif runtime_type == "llm_direct":
        candidates.append(("llm_direct", _llm))
    else:  # auto
        if claude_code.is_available():
            candidates.append(("claude_code", _run_claude_code))
        if llm.is_available():
            candidates.append(("llm_direct", _llm))

    for name, fn in candidates:
        try:
            log.info("dispatching trigger=%r → runtime=%s", trigger.name, name)
            text = await fn(system_prompt, user_message, event)
            if text:
                return text
            log.warning("runtime %s returned empty reply, trying next", name)
        except claude_code.AlreadyRunning:
            # Don't fall through to llm_direct — the duplicate-activation
            # signal must propagate so _fire_trigger can skip cleanly.
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("runtime %s failed: %s", name, e)

    log.info("no runtime succeeded — falling back to template")
    return _confirmation_comment(trigger)


def _ticket_workspace(ticket_id: str) -> str:
    """Per-ticket persistent workspace dir under ~/.coii/tickets/<id>/.

    State (files, branches, scratch notes) survives across multiple
    activations on the same ticket so the agent can resume mid-flight work.
    """
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in ticket_id)
    path = coii_root() / "tickets" / safe_id
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


# Paths the CLI is allowed to read/write beyond its workspace cwd.
# Adding ~/Desktop / ~/Documents / ~/Downloads here only helps if the
# parent shell (Terminal.app) has macOS Full Disk Access — otherwise TCC
# blocks the writes regardless of what claude is told it can touch.
# Override per Agent via workspace.json `extra_dirs` (planned), or
# via the env var below.
_DEFAULT_EXTRA_DIRS: tuple[str, ...] = tuple(
    p.strip() for p in os.getenv("AGENTS_EXTRA_DIRS", "~/Desktop").split(",")
    if p.strip()
)


async def _run_claude_code(
    system_prompt: str, user_message: str, event: TicketEvent,
) -> str:
    return await claude_code.generate_reply(
        system_prompt=system_prompt,
        user_message=user_message,
        workspace_dir=_ticket_workspace(event.ticket.id),
        extra_dirs=_DEFAULT_EXTRA_DIRS,
        enable_tools=True,
    )


async def _run_llm_direct(
    system_prompt: str, user_message: str, event: TicketEvent,
    *, model_spec: str | None = None,
) -> str:
    return await llm.generate_reply(
        system_prompt=system_prompt,
        user_message=user_message,
        model_spec=model_spec,
    )


def _confirmation_comment(trigger: Trigger) -> str:
    """Templated fallback — used when LLM is unavailable."""
    return (
        f"@{trigger.agent} Acknowledged. Trigger: **{trigger.name}**\n\n"
        f"Workflow:\n```\n{trigger.workflow}\n```\n\n"
        "(LLM runtime not configured — replying with template.)"
    )


async def _fetch_history(adapter: LinearAdapter, ticket_id: str) -> list[Comment]:
    """Pull the full Linear comment history for this ticket.

    This is the *durable conversation log*. Each activation reads it fresh,
    which means: (a) catch-up after server downtime works for free — no
    webhooks to replay; (b) the agent sees its own past replies, replacing
    the role of a persistent claude session; (c) Linear stays the single
    source of truth, local state is pure cache.

    Failure here is non-fatal — we'd rather run with sparse context than
    drop the activation. The triggering event still has the latest comment
    body in its raw payload as a fallback.
    """
    if not ticket_id:
        return []
    try:
        return await adapter.list_comments(ticket_id)
    except Exception as e:  # noqa: BLE001
        log.warning("failed to fetch comment history for %s: %s — using sparse context", ticket_id, e)
        return []


def _user_message(
    event: TicketEvent, trigger: Trigger, history: list[Comment],
) -> str:
    """Build the user message: ticket context + workflow + full conversation history."""
    t = event.ticket
    parts: list[str] = []

    parts.append(f"# Activation: {event.type}\n")
    parts.append(f"Trigger fired: **{trigger.name}**\n")
    if trigger.workflow:
        parts.append(f"\n## Workflow for this activation\n\n{trigger.workflow}\n")

    parts.append("\n## Ticket\n")
    parts.append(f"- id: `{t.id}`")
    parts.append(f"- title: {t.title}")
    parts.append(f"- status: {t.status or '—'}")
    parts.append(f"- assignee: {t.assignee or '—'}")
    parts.append(f"- project: {t.project or '—'}")
    parts.append(f"- team: {t.team or '—'}")
    parts.append(f"- labels: {', '.join(t.labels) if t.labels else '—'}")
    parts.append(f"- url: {t.url}")
    if t.description:
        parts.append(f"\n### Description\n\n{t.description}")

    # Render the full conversation transcript. The agent sees both human
    # comments AND its own past replies — that's the substitute for a
    # persistent claude session.
    triggering_id = (event.raw.get("data") or {}).get("id")
    triggering_body = (event.raw.get("data") or {}).get("body")
    parts.append(_render_history(history, triggering_id, triggering_body, event))

    parts.append(
        "\n## Your task\n\n"
        "Reply in character as defined by your Agent files. You have full "
        "tool access (bash, read, write, edit, glob, grep). **Your current "
        "working directory IS your per-ticket workspace** — write files there "
        "by default. If the ticket asks you to create a file at a path outside "
        "your workspace (e.g. `~/Desktop/...`) and the host hasn't granted "
        "access, write into your workspace and report the file's location in "
        "your reply — the human will move it. **Do the work, then summarize** — "
        "your final stdout is posted verbatim as a Linear comment, so make the "
        "last paragraph a clear, human-readable summary of what you actually "
        "did (or what's blocking you).\n\n"
        "**Memory model:** you are running as a fresh process. The "
        "`Conversation history` section above contains every prior comment "
        "on this ticket, including your own past replies — treat it as your "
        "memory of what's already happened. Don't redo work you already did "
        "in an earlier reply; build on it. The triggering comment is marked "
        "`← TRIGGERING THIS ACTIVATION`."
        "\n\n"
        "## Status control\n\n"
        "You can request a Linear status transition by ending your reply with "
        "a tag of the form `<status>STATE</status>` or `<status>STATE: reason</status>`. "
        "STATE must match a workflow state name in this Linear workspace exactly. "
        "Common states include `In Progress`, `Done`, `Backlog`, `Canceled`. "
        "Use:\n"
        "- `<status>Done</status>` when you've completed the work and a human just needs to review.\n"
        "- `<status>Blocked: <reason></status>` if your workspace lacks a `Blocked` "
        "  state, the closest fallback is `Backlog` — use `<status>Backlog: <reason></status>` "
        "  in that case. Do NOT invent state names.\n"
        "- Omit the tag entirely to leave status unchanged.\n"
        "The tag is stripped from the comment before posting; the transition is "
        "applied automatically. If the state name doesn't exist in the workspace, "
        "the transition will fail and a note will be appended to your comment."
    )
    return "\n".join(parts)


def _render_history(
    history: list[Comment],
    triggering_id: str | None,
    triggering_body: str | None,
    event: TicketEvent,
) -> str:
    """Render conversation history as a markdown transcript.

    Marks one entry as the comment that triggered THIS activation so the
    agent knows where the user's latest input is. If the triggering comment
    wasn't fetched yet (race between webhook and GraphQL read), append it
    inline with the same marker.
    """
    if not history and not triggering_body:
        return ""

    lines: list[str] = ["\n## Conversation history\n"]
    seen_triggering = False
    for c in history:
        marker = ""
        if triggering_id and c.id == triggering_id:
            marker = "  ← TRIGGERING THIS ACTIVATION"
            seen_triggering = True
        who = "**you** (agent)" if c.is_agent else c.author
        when = c.created_at or "?"
        lines.append(f"\n### [{when}] {who}{marker}\n\n{c.body}\n")

    # Race fallback: comment landed but isn't in the GraphQL response yet.
    if (
        event.type == "ticket.commented"
        and triggering_body
        and not seen_triggering
    ):
        actor = event.actor or "unknown"
        lines.append(
            f"\n### [now] {actor}  ← TRIGGERING THIS ACTIVATION\n\n{triggering_body}\n"
        )

    return "".join(lines)


def _final_prompt(ctx: AgentContext, trigger: Trigger, event: TicketEvent) -> str:
    """Append trigger.workflow + ticket context to the workspace prompt.

    PRD §7.4 ordering:
      [system context]
      [identity files]
      [memory tier 1+2]      <-- ctx.prompt up to here
      [trigger.workflow]
      [current ticket info]
    """
    parts: list[str] = [ctx.prompt]
    if trigger.workflow:
        parts.append(
            "\n\n<!-- workflow (from trigger) -->\n"
            f"# Workflow for this activation\n\nTrigger: {trigger.name}\n\n"
            f"{trigger.workflow}\n"
        )
    parts.append(_ticket_block(event))
    return "".join(parts)


def _ticket_block(event: TicketEvent) -> str:
    t = event.ticket
    labels = ", ".join(t.labels) if t.labels else "—"
    return (
        "\n\n<!-- current ticket -->\n"
        f"# Current ticket ({event.type})\n\n"
        f"- id: `{t.id}`\n"
        f"- title: {t.title}\n"
        f"- status: {t.status}\n"
        f"- assignee: {t.assignee}\n"
        f"- project: {t.project}\n"
        f"- team: {t.team}\n"
        f"- labels: {labels}\n"
        f"- url: {t.url}\n\n"
        f"## Description\n\n{t.description or '(empty)'}\n"
    )
