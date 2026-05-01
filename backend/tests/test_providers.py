"""Provider registry/parser tests.

Network and API-key behavior is covered indirectly: we mock the env to
flip ``is_available`` on/off and assert ``any_available`` / ``resolve``
react correctly. We do NOT exercise real network calls here — those
belong in an integration suite gated by real credentials.
"""

from __future__ import annotations

import pytest

from app.runtimes.providers import (
    DEFAULT_SPEC,
    ProviderError,
    any_available,
    default_spec,
    get_provider,
    parse_model_spec,
    resolve,
)


class TestParseModelSpec:
    def test_basic(self):
        assert parse_model_spec("openai/gpt-4o") == ("openai", "gpt-4o")
        assert parse_model_spec("anthropic/claude-sonnet-4-6") == (
            "anthropic", "claude-sonnet-4-6",
        )

    def test_lowercases_provider(self):
        assert parse_model_spec("OpenAI/gpt-4o") == ("openai", "gpt-4o")

    def test_strips_whitespace(self):
        assert parse_model_spec("  openai  /  gpt-4o  ") == ("openai", "gpt-4o")

    def test_keeps_slashes_in_model_id(self):
        # Future-proofing for HuggingFace-style ids; we split on FIRST slash only.
        assert parse_model_spec("hf/meta-llama/Llama-3-8B") == (
            "hf", "meta-llama/Llama-3-8B",
        )

    @pytest.mark.parametrize("bad", ["", "openai", "/gpt-4o", "openai/", "  /  "])
    def test_rejects_malformed(self, bad):
        with pytest.raises(ProviderError):
            parse_model_spec(bad)


class TestGetProvider:
    def test_anthropic_registered(self):
        p = get_provider("anthropic")
        assert p.name == "anthropic"

    def test_openai_registered(self):
        p = get_provider("openai")
        assert p.name == "openai"

    def test_singleton(self):
        assert get_provider("openai") is get_provider("openai")

    def test_unknown_raises(self):
        with pytest.raises(ProviderError, match="unknown provider"):
            get_provider("nonexistent")


class TestResolve:
    def test_explicit_spec(self):
        provider, model_id = resolve("openai/gpt-4o")
        assert provider.name == "openai"
        assert model_id == "gpt-4o"

    def test_none_uses_default(self, monkeypatch):
        monkeypatch.delenv("LLM_MODEL", raising=False)
        provider, model_id = resolve(None)
        # Default spec is anthropic/...
        expected_provider, expected_model = DEFAULT_SPEC.split("/", 1)
        assert provider.name == expected_provider
        assert model_id == expected_model

    def test_env_var_overrides_default(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "openai/gpt-5")
        provider, model_id = resolve(None)
        assert provider.name == "openai"
        assert model_id == "gpt-5"


class TestAvailability:
    def test_any_available_true_with_anthropic_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert any_available()

    def test_any_available_true_with_openai_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert any_available()

    def test_any_available_false_when_no_keys(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert not any_available()


class TestDefaultSpec:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("LLM_MODEL", raising=False)
        assert default_spec() == DEFAULT_SPEC

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o")
        assert default_spec() == "openai/gpt-4o"

    def test_blank_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "   ")
        assert default_spec() == DEFAULT_SPEC
