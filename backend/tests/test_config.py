"""Tests for app.config — schema, SecretRef, env chain, v1 migration."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app import config


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# parse_ref
# ---------------------------------------------------------------------------


class TestParseRef:
    def test_none_and_empty(self):
        assert config.parse_ref(None) is None
        assert config.parse_ref("") is None

    def test_string_becomes_literal(self):
        ref = config.parse_ref("sk-baked-in")
        assert ref is not None
        assert ref.source == "literal"
        assert ref.value == "sk-baked-in"

    def test_env_ref(self):
        ref = config.parse_ref({"source": "env", "id": "FOO"})
        assert ref is not None
        assert ref.source == "env"
        assert ref.id == "FOO"

    def test_unknown_source_dropped(self):
        assert config.parse_ref({"source": "vault", "id": "x"}) is None

    def test_exec_args_normalized(self):
        ref = config.parse_ref({
            "source": "exec",
            "command": "/usr/bin/op",
            "args": ["read", "op://x"],
        })
        assert ref is not None
        assert ref.command == "/usr/bin/op"
        assert ref.args == ("read", "op://x")


# ---------------------------------------------------------------------------
# resolve_ref
# ---------------------------------------------------------------------------


class TestResolveRef:
    def test_env_present(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "abc")
        ref = config.parse_ref({"source": "env", "id": "MY_KEY"})
        assert config.resolve_ref(ref) == "abc"

    def test_env_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_KEY", raising=False)
        ref = config.parse_ref({"source": "env", "id": "MISSING_KEY"})
        assert config.resolve_ref(ref) is None

    def test_literal(self):
        ref = config.SecretRef(source="literal", value="raw")
        assert config.resolve_ref(ref) == "raw"

    def test_file_plain(self, tmp_path):
        p = tmp_path / "secret.txt"
        p.write_text("the-token\n")
        ref = config.SecretRef(source="file", path=str(p))
        assert config.resolve_ref(ref) == "the-token"

    def test_file_json_key(self, tmp_path):
        p = tmp_path / "secrets.json"
        p.write_text(json.dumps({"linear": {"api_key": "xyz"}}))
        ref = config.SecretRef(source="file", path=str(p), key="linear.api_key")
        assert config.resolve_ref(ref) == "xyz"

    def test_none(self):
        assert config.resolve_ref(None) is None


# ---------------------------------------------------------------------------
# load() — fresh / v2
# ---------------------------------------------------------------------------


class TestLoadV2:
    def test_missing_file_yields_defaults(self):
        cfg = config.load()
        assert cfg.version == config.CONFIG_VERSION
        assert cfg.service.name == "coii"
        assert cfg.linear.enabled is True
        assert cfg.linear.poll_interval_seconds == 30

    def test_v2_round_trip(self, coii_dir, monkeypatch):
        _write(coii_dir / "config.json", {
            "version": 2,
            "service": {"name": "coii", "log_level": "debug"},
            "trackers": {
                "linear": {
                    "enabled": True,
                    "api_key": {"source": "env", "id": "LINEAR_API_KEY"},
                    "webhook_secret": {"source": "env", "id": "LINEAR_WEBHOOK_SECRET"},
                    "team_keys": ["lel", "eng"],
                    "poll_interval_seconds": 45,
                }
            },
            "models": {
                "default": "openai/gpt-4o",
                "providers": {
                    "openai": {"type": "openai", "api_key": {"source": "env", "id": "OPENAI_API_KEY"}},
                },
            },
            "runtimes": {"default": {"type": "claude_code", "command": "claude"}},
            "memory": {"search": {"engine": "ripgrep"}},
        })
        monkeypatch.setenv("LINEAR_API_KEY", "lin-key")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-x")

        cfg = config.load()
        assert cfg.service.log_level == "debug"
        assert cfg.linear.team_keys == ("LEL", "ENG")  # uppercased
        assert cfg.linear.poll_interval_seconds == 45
        assert cfg.linear.api_key == "lin-key"
        assert cfg.models.default == "openai/gpt-4o"
        assert cfg.models.providers["openai"].api_key == "sk-x"

    def test_provider_base_url_round_trip(self, coii_dir, monkeypatch):
        _write(coii_dir / "config.json", {
            "version": 2,
            "models": {
                "providers": {
                    "anthropic": {
                        "type": "anthropic",
                        "api_key": {"source": "env", "id": "ANTHROPIC_API_KEY"},
                        "base_url": "https://proxy.example.com",
                    },
                    "openai": {  # no base_url → falls through
                        "type": "openai",
                        "api_key": {"source": "env", "id": "OPENAI_API_KEY"},
                    },
                },
            },
        })
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-x")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
        cfg = config.load()
        assert cfg.models.providers["anthropic"].base_url == "https://proxy.example.com"
        assert cfg.models.providers["openai"].base_url is None


# ---------------------------------------------------------------------------
# Migrations — forward-only
# ---------------------------------------------------------------------------


class TestMigrations:
    def test_empty_registry_at_current_version_is_noop(self, coii_dir):
        """Default state: no migrations registered, config already at
        CONFIG_VERSION → load() does not rewrite the file."""
        path = coii_dir / "config.json"
        _write(path, {"version": config.CONFIG_VERSION})
        before = path.read_text()
        config.load(path)
        assert path.read_text() == before  # unchanged on disk

    def test_runs_pending_migration_and_persists(self, coii_dir, monkeypatch):
        """A registered migration runs at load() and the upgraded shape
        is written back so we don't re-migrate next load."""
        path = coii_dir / "config.json"
        _write(path, {"version": 1, "old_field": "value"})

        def _v1_to_v2(raw: dict) -> dict:
            raw["new_field"] = raw.pop("old_field", "")
            return raw

        # Register a fake v1→v2 step. CONFIG_VERSION=2 → loop runs once.
        monkeypatch.setitem(config.MIGRATIONS, 1, _v1_to_v2)

        config.load(path)
        # Persisted: file now reflects v2 shape.
        on_disk = json.loads(path.read_text())
        assert on_disk["version"] == 2
        assert on_disk["new_field"] == "value"
        assert "old_field" not in on_disk

        # Second load is a no-op (already at CONFIG_VERSION).
        before = path.read_text()
        config.load(path)
        assert path.read_text() == before

    def test_missing_migration_raises_actionable_error(self, coii_dir, monkeypatch):
        """If the user's config is below CONFIG_VERSION but no migration
        is registered for that step, raise with the recovery hint."""
        path = coii_dir / "config.json"
        _write(path, {"version": 0})  # impossibly old
        # CONFIG_VERSION is 2; no migration from 0 registered.
        monkeypatch.setattr(config, "MIGRATIONS", {})
        with pytest.raises(RuntimeError, match="no registered migration"):
            config.load(path)

    def test_in_memory_upgrade_when_persist_fails(
        self, coii_dir, monkeypatch, caplog,
    ):
        """If we can't write the file (read-only fs, perm denied), we
        still hand back the migrated Config in memory and log."""
        path = coii_dir / "config.json"
        _write(path, {"version": 1})

        def _v1_to_v2(raw: dict) -> dict:
            raw["bumped"] = True
            return raw

        monkeypatch.setitem(config.MIGRATIONS, 1, _v1_to_v2)

        # Make the file read-only so the persist write raises.
        path.chmod(0o400)
        try:
            cfg = config.load(path)
        finally:
            path.chmod(0o600)
        # The in-memory Config carries the upgrade
        assert cfg.raw["version"] == 2
        assert cfg.raw["bumped"] is True
        # Disk still at v1 (write failed, warning logged)
        assert json.loads(path.read_text())["version"] == 1


# ---------------------------------------------------------------------------
# env precedence chain
# ---------------------------------------------------------------------------


class TestEnvChain:
    def test_config_env_block_fills_missing(self, coii_dir, monkeypatch):
        monkeypatch.delenv("FROM_BLOCK", raising=False)
        _write(coii_dir / "config.json", {
            "version": 2,
            "env": {"FROM_BLOCK": "yes"},
        })
        config.load()
        assert os.environ["FROM_BLOCK"] == "yes"

    def test_process_env_wins_over_block(self, coii_dir, monkeypatch):
        monkeypatch.setenv("FROM_BLOCK", "process-wins")
        _write(coii_dir / "config.json", {
            "version": 2,
            "env": {"FROM_BLOCK": "block-loses"},
        })
        config.load()
        assert os.environ["FROM_BLOCK"] == "process-wins"

    def test_home_env_fills_missing(self, tmp_path, coii_dir, monkeypatch):
        # The conftest disables both repo + home dotenv. Override just
        # `home_env_path` to point at a tmp .env so we exercise the loader
        # without re-enabling the repo .env (which would leak the dev's keys).
        env_path = tmp_path / "home.env"
        env_path.write_text("FROM_HOME=present\n")
        monkeypatch.setattr(config, "home_env_path", lambda: env_path)
        monkeypatch.delenv("FROM_HOME", raising=False)
        _write(coii_dir / "config.json", {"version": 2})
        config.load()
        assert os.environ.get("FROM_HOME") == "present"
