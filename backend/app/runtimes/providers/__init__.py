"""LLM provider registry.

Adds support for new providers (Google, DeepSeek, Bedrock, ...) by:
  1. Implementing ``LLMProvider`` in a new module here.
  2. Registering it in ``_REGISTRY`` below.

Callers use ``resolve(spec)`` to turn a ``<provider>/<model-id>`` string
into a (provider, model_id) pair. The spec format mirrors openclaw and
LiteLLM so users can copy-paste model identifiers between projects.

Example specs:
  - ``anthropic/claude-sonnet-4-6``
  - ``anthropic/claude-opus-4-7``
  - ``openai/gpt-4o``
  - ``openai/gpt-5``
"""

from __future__ import annotations

import os
from typing import Callable

from app import config

from .anthropic_provider import AnthropicProvider
from .base import LLMProvider, ProviderError
from .openai_provider import OpenAIProvider

DEFAULT_SPEC = "anthropic/claude-sonnet-4-6"

# name -> factory. Factories are called lazily so missing optional deps in
# a never-used provider don't break import.
_REGISTRY: dict[str, Callable[[], LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}

_INSTANCES: dict[str, LLMProvider] = {}


def parse_model_spec(spec: str) -> tuple[str, str]:
    """Split a ``<provider>/<model-id>`` spec.

    Raises ProviderError on a malformed spec. Splits on the first ``/``
    only — model ids never contain slashes today, but if a future provider
    uses HuggingFace-style ``org/model`` ids the rest will pass through.
    """
    if not spec or "/" not in spec:
        raise ProviderError(
            f"invalid model spec {spec!r}: expected '<provider>/<model-id>' "
            f"(e.g. 'openai/gpt-4o', 'anthropic/claude-sonnet-4-6')"
        )
    provider_name, model_id = spec.split("/", 1)
    provider_name = provider_name.strip().lower()
    model_id = model_id.strip()
    if not provider_name or not model_id:
        raise ProviderError(f"invalid model spec {spec!r}: empty provider or model id")
    return provider_name, model_id


def get_provider(name: str) -> LLMProvider:
    """Return a singleton provider instance by name."""
    name = name.strip().lower()
    if name not in _REGISTRY:
        raise ProviderError(
            f"unknown provider {name!r}; registered: {sorted(_REGISTRY)}"
        )
    if name not in _INSTANCES:
        _INSTANCES[name] = _REGISTRY[name]()
    return _INSTANCES[name]


def resolve(spec: str | None) -> tuple[LLMProvider, str]:
    """Resolve a spec (or ``None`` -> default) into (provider, model_id)."""
    return _resolve_spec(spec or default_spec())


def _resolve_spec(spec: str) -> tuple[LLMProvider, str]:
    provider_name, model_id = parse_model_spec(spec)
    return get_provider(provider_name), model_id


def default_spec() -> str:
    """Default model spec.

    Order: ``LLM_MODEL`` env (transitional override) →
    ``models.default`` from config.json → built-in fallback.
    """
    env_override = os.getenv("LLM_MODEL", "").strip()
    if env_override:
        return env_override
    return config.get().models.default or DEFAULT_SPEC


def any_available() -> bool:
    """True iff at least one registered provider has credentials."""
    return any(get_provider(n).is_available() for n in _REGISTRY)


__all__ = [
    "DEFAULT_SPEC",
    "LLMProvider",
    "ProviderError",
    "any_available",
    "default_spec",
    "get_provider",
    "parse_model_spec",
    "resolve",
]
