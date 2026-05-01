"""Direct LLM runtime — multi-provider dispatch.

When a trigger fires, we send the assembled Agent prompt as the system
prompt and the ticket context + workflow + last comment as the user
message. The selected provider generates a real reply that we post back
to Linear.

Provider selection (highest precedence first):
  1. ``model_spec`` argument passed by the caller (per-trigger override)
  2. ``LLM_MODEL`` env var (e.g. ``openai/gpt-4o``)
  3. ``DEFAULT_SPEC`` from ``providers/__init__.py``

Caching: the system prompt is stable across calls (Agent identity +
memory). The provider implementation marks it cacheable; whether caching
actually kicks in depends on the provider and the prefix size.

The Phase-2 Claude Code CLI runtime in ``claude_code.py`` is unrelated —
it shells out to the local ``claude`` binary and uses OAuth, not these
API providers.
"""

from __future__ import annotations

import logging

from app.runtimes.providers import (
    ProviderError,
    any_available,
    default_spec,
    resolve,
)

log = logging.getLogger(__name__)


def is_available() -> bool:
    """True iff *any* registered provider has credentials configured."""
    return any_available()


async def generate_reply(
    *,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
    model_spec: str | None = None,
) -> str:
    """Generate a single conversational reply via the configured provider.

    Returns the assistant text (concatenated text blocks). Empty string
    if the provider returned no text content.
    """
    spec = model_spec or default_spec()
    try:
        provider, model_id = resolve(spec)
    except ProviderError as e:
        log.error("cannot resolve model spec %r: %s", spec, e)
        raise

    log.info("dispatching llm reply: provider=%s model=%s", provider.name, model_id)
    return await provider.generate_reply(
        model=model_id,
        system_prompt=system_prompt,
        user_message=user_message,
        max_tokens=max_tokens,
    )
