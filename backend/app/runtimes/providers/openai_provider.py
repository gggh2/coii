"""OpenAI provider — Chat Completions API.

Uses Chat Completions because it's the most widely-implemented surface:
GPT-4o / GPT-5 family, plus most "OpenAI-compatible" gateways (DeepSeek,
Together, Fireworks, vLLM, Ollama). If an OpenAI-compatible endpoint is
the goal, set ``OPENAI_BASE_URL`` and reuse this class — the SDK reads
the env var natively.

Native support for non-OpenAI providers (DeepSeek's own SDK, Google
Gemini, Bedrock, ...) lives in its own provider module so each can
expose provider-specific knobs (safety settings, region, etc.) without
contorting this class.
"""

from __future__ import annotations

import logging
import os

from openai import AsyncOpenAI

from app import config

from .base import LLMProvider, ProviderError

log = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None

    def _resolved_api_key(self) -> str | None:
        provider = config.get().models.providers.get("openai")
        if provider is not None:
            v = provider.api_key
            if v:
                return v
        return os.getenv("OPENAI_API_KEY") or None

    def _resolved_base_url(self) -> str | None:
        provider = config.get().models.providers.get("openai")
        if provider is not None and provider.base_url:
            return provider.base_url
        return os.getenv("OPENAI_BASE_URL") or None

    def is_available(self) -> bool:
        return bool(self._resolved_api_key())

    def _client_singleton(self) -> AsyncOpenAI:
        if self._client is None:
            api_key = self._resolved_api_key()
            base_url = self._resolved_base_url()
            kwargs: dict[str, str] = {}
            if api_key:
                kwargs["api_key"] = api_key
            if base_url:
                kwargs["base_url"] = base_url
                log.info("openai client: base_url=%s", base_url)
            self._client = AsyncOpenAI(**kwargs)
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
            raise ProviderError("OpenAI API key not configured")

        client = self._client_singleton()
        response = await client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )

        usage = response.usage
        log.info(
            "openai reply: model=%s in=%s out=%s stop=%s",
            model,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
            response.choices[0].finish_reason if response.choices else None,
        )

        if not response.choices:
            return ""
        content = response.choices[0].message.content or ""
        return content.strip()
