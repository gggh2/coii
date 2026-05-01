"""LLM provider interface.

Every concrete provider implements `LLMProvider`. The registry in
`__init__.py` maps a `<provider>/<model-id>` spec (e.g. ``openai/gpt-4o``,
``anthropic/claude-sonnet-4-6``) to a provider instance.

The interface is intentionally narrow — just enough for the Phase-1.5
"plan out loud" flow in `runtimes/llm.py`. Tool use, streaming, and
multi-turn live in separate methods we'll add when a caller needs them,
not on speculation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """One concrete LLM backend (Anthropic, OpenAI, Google, ...)."""

    name: str

    @abstractmethod
    def is_available(self) -> bool:
        """True iff this provider has credentials configured to be callable now."""

    @abstractmethod
    async def generate_reply(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1024,
    ) -> str:
        """Single-shot reply. Returns concatenated assistant text (may be empty)."""


class ProviderError(RuntimeError):
    """Raised when a provider cannot service a request (missing key, bad spec)."""
