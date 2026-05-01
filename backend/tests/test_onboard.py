"""Tests for the pure helpers used by the setup wizard.

The interactive shell isn't tested here — these cover the file rendering,
parsing, merging, provider lookup, and config-mutation helpers that the
shell composes.

Importing via the legacy ``onboard`` shim keeps the test surface stable
while the actual code now lives at ``app.setup_wizard``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ isn't a package; load it the same way `./onboard` does.
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import onboard  # noqa: E402


class TestParseEnvFile:
    def test_basic(self):
        text = "KEY=value\nOTHER=x\n"
        assert onboard.parse_env_file(text) == {"KEY": "value", "OTHER": "x"}

    def test_ignores_comments_and_blanks(self):
        text = "# header\n\nKEY=value\n# inline\nOTHER=x\n"
        assert onboard.parse_env_file(text) == {"KEY": "value", "OTHER": "x"}

    def test_strips_surrounding_quotes(self):
        text = 'KEY="quoted"\nOTHER=\'single\'\nBARE=plain\n'
        assert onboard.parse_env_file(text) == {
            "KEY": "quoted", "OTHER": "single", "BARE": "plain",
        }

    def test_keeps_inner_chars_with_equals(self):
        # values may contain '=' (bearer tokens, base64). Only first '=' splits.
        text = "TOKEN=Bearer abc=def==\n"
        assert onboard.parse_env_file(text) == {"TOKEN": "Bearer abc=def=="}

    def test_last_wins(self):
        assert onboard.parse_env_file("X=1\nX=2\n") == {"X": "2"}

    def test_skips_lines_without_equals(self):
        assert onboard.parse_env_file("garbage\nX=1\n") == {"X": "1"}


class TestRenderEnvFile:
    def test_emits_known_keys_in_section_order(self):
        out = onboard.render_env_file({
            "LINEAR_API_KEY": "tok",
            "LLM_MODEL": "openai/gpt-4o",
            "OPENAI_API_KEY": "sk-x",
        })
        # Linear section appears before LLM section.
        assert out.index("LINEAR_API_KEY") < out.index("LLM_MODEL")
        # Bare KEY= for unset values.
        assert "ANTHROPIC_API_KEY=\n" in out

    def test_preserves_unknown_keys(self):
        out = onboard.render_env_file({"WEIRD_CUSTOM_KEY": "x"})
        assert "WEIRD_CUSTOM_KEY=x" in out
        assert "extra keys preserved" in out

    def test_round_trip(self):
        original = {
            "LINEAR_API_KEY": "tok",
            "LINEAR_TEAM_KEY": "ENG",
            "LINEAR_WEBHOOK_SECRET": "sec",
            "LLM_MODEL": "openai/gpt-4o",
            "OPENAI_API_KEY": "sk-x",
            "LOG_LEVEL": "INFO",
        }
        rendered = onboard.render_env_file(original)
        parsed = onboard.parse_env_file(rendered)
        for k, v in original.items():
            assert parsed[k] == v


class TestMergeEnv:
    def test_new_overrides(self):
        existing = {"A": "1", "B": "2"}
        out = onboard.merge_env(existing, {"B": "new"})
        assert out == {"A": "1", "B": "new"}

    def test_empty_new_value_kept_from_existing(self):
        # The interactive shell omits a key when the user hits enter, so
        # blank inputs must NEVER wipe an existing value.
        existing = {"A": "kept"}
        out = onboard.merge_env(existing, {"A": ""})
        assert out == {"A": "kept"}

    def test_adds_new_keys(self):
        out = onboard.merge_env({"A": "1"}, {"B": "2"})
        assert out == {"A": "1", "B": "2"}


class TestGenerateWebhookSecret:
    def test_length_and_charset(self):
        s = onboard.generate_webhook_secret()
        assert len(s) == 64
        assert all(c in "0123456789abcdef" for c in s)

    def test_unique_each_call(self):
        a = onboard.generate_webhook_secret()
        b = onboard.generate_webhook_secret()
        assert a != b


class TestProviderRegistry:
    def test_two_providers_known(self):
        names = {p.name for p in onboard.PROVIDER_CHOICES}
        assert names == {"anthropic", "openai"}

    def test_find_provider(self):
        anthropic = onboard.find_provider("anthropic")
        assert anthropic is not None
        assert anthropic.env_key == "ANTHROPIC_API_KEY"
        assert anthropic.default_model.startswith("anthropic/")
        openai = onboard.find_provider("openai")
        assert openai is not None
        assert openai.env_key == "OPENAI_API_KEY"
        assert openai.default_model.startswith("openai/")

    def test_unknown_provider_returns_none(self):
        assert onboard.find_provider("nonexistent") is None


class TestNonInteractiveCollect:
    """`_collect_non_interactive` reads from env vars instead of prompts."""

    def test_minimum_env(self, monkeypatch):
        monkeypatch.setenv("LINEAR_API_KEY", "lin-tok")
        monkeypatch.setenv("LINEAR_TEAM_KEY", "LEL")
        monkeypatch.delenv("COII_WIZARD_PROVIDER", raising=False)
        monkeypatch.delenv("LINEAR_WEBHOOK_SECRET", raising=False)
        monkeypatch.delenv("COII_WIZARD_LOG_LEVEL", raising=False)
        new_env, cfg_updates, team_key = onboard._collect_non_interactive({}, {})
        assert team_key == "LEL"
        assert new_env["LINEAR_API_KEY"] == "lin-tok"
        assert new_env["LINEAR_TEAM_KEY"] == "LEL"
        # Webhook secret + log level only land in output when env vars set them.
        assert "LINEAR_WEBHOOK_SECRET" not in new_env
        assert cfg_updates == {"team_keys": ("LEL",)}

    def test_with_provider(self, monkeypatch):
        monkeypatch.setenv("LINEAR_API_KEY", "lin-tok")
        monkeypatch.setenv("LINEAR_TEAM_KEY", "ENG")
        monkeypatch.setenv("COII_WIZARD_PROVIDER", "anthropic")
        monkeypatch.setenv("COII_WIZARD_API_KEY", "ant-key")
        monkeypatch.setenv("COII_WIZARD_MODEL", "anthropic/claude-haiku-4-5-20251001")
        new_env, cfg_updates, _ = onboard._collect_non_interactive({}, {})
        assert new_env["ANTHROPIC_API_KEY"] == "ant-key"
        assert cfg_updates["model_spec"] == "anthropic/claude-haiku-4-5-20251001"

    def test_missing_linear_key_raises(self, monkeypatch):
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        monkeypatch.setenv("LINEAR_TEAM_KEY", "LEL")
        with pytest.raises(SystemExit, match="LINEAR_API_KEY"):
            onboard._collect_non_interactive({}, {})

    def test_missing_team_key_is_optional(self, monkeypatch):
        """v1 ships poller-only; team key is now optional. Polling stays disabled
        until the user sets ``trackers.linear.team_keys`` later."""
        monkeypatch.setenv("LINEAR_API_KEY", "x")
        monkeypatch.delenv("LINEAR_TEAM_KEY", raising=False)
        new_env, cfg_updates, team_key = onboard._collect_non_interactive({}, {})
        assert team_key == ""
        assert "LINEAR_TEAM_KEY" not in new_env
        assert "team_keys" not in cfg_updates

    def test_invalid_team_key_raises(self, monkeypatch):
        monkeypatch.setenv("LINEAR_API_KEY", "x")
        monkeypatch.setenv("LINEAR_TEAM_KEY", "1bad")
        with pytest.raises(SystemExit, match="LINEAR_TEAM_KEY"):
            onboard._collect_non_interactive({}, {})

    def test_provider_without_api_key_raises(self, monkeypatch):
        monkeypatch.setenv("LINEAR_API_KEY", "x")
        monkeypatch.setenv("LINEAR_TEAM_KEY", "LEL")
        monkeypatch.setenv("COII_WIZARD_PROVIDER", "openai")
        monkeypatch.delenv("COII_WIZARD_API_KEY", raising=False)
        with pytest.raises(SystemExit, match="COII_WIZARD_API_KEY"):
            onboard._collect_non_interactive({}, {})

    def test_existing_secret_preserved(self, monkeypatch):
        monkeypatch.setenv("LINEAR_API_KEY", "lin")
        monkeypatch.setenv("LINEAR_TEAM_KEY", "LEL")
        monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", "preserved-secret")
        new_env, _, _ = onboard._collect_non_interactive({}, {})
        assert new_env["LINEAR_WEBHOOK_SECRET"] == "preserved-secret"


class TestApplyToConfig:
    """The wizard's bridge from interactive answers to config.json mutations."""

    def test_writes_only_provided_fields(self):
        cfg: dict = {"version": 2, "service": {"log_level": "info"}}
        onboard.apply_to_config(cfg, log_level="debug")
        assert cfg["service"]["log_level"] == "debug"
        # everything else untouched
        assert cfg["version"] == 2

    def test_team_keys_array(self):
        cfg: dict = {"version": 2}
        onboard.apply_to_config(cfg, team_keys=("LEL", "ENG"))
        assert cfg["trackers"]["linear"]["team_keys"] == ["LEL", "ENG"]

    def test_model_spec(self):
        cfg: dict = {"version": 2}
        onboard.apply_to_config(cfg, model_spec="openai/gpt-4o")
        assert cfg["models"]["default"] == "openai/gpt-4o"

    def test_skips_when_arg_omitted(self):
        cfg: dict = {"version": 2, "service": {"log_level": "info"}}
        onboard.apply_to_config(cfg)  # no kwargs
        # nothing added
        assert cfg == {"version": 2, "service": {"log_level": "info"}}
