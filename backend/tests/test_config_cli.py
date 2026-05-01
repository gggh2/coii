"""Tests for app.config_cli — path navigation + get/set/unset commands."""

from __future__ import annotations

import json

import pytest

from app import config, config_cli


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestSplitPath:
    def test_dot(self):
        assert config_cli.split_path("a.b.c") == ["a", "b", "c"]

    def test_brackets(self):
        assert config_cli.split_path("a.b[0].c") == ["a", "b", 0, "c"]

    def test_multiple_brackets(self):
        assert config_cli.split_path("a[0][1].b") == ["a", 0, 1, "b"]

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            config_cli.split_path(".a")


class TestGetAt:
    def test_basic(self):
        obj = {"a": {"b": [{"c": 7}]}}
        assert config_cli.get_at(obj, ["a", "b", 0, "c"]) == 7

    def test_missing_returns_none(self):
        assert config_cli.get_at({"a": 1}, ["a", "b"]) is None
        assert config_cli.get_at({"a": [1]}, ["a", 5]) is None


class TestSetAt:
    def test_creates_intermediate_dicts(self):
        obj: dict = {}
        config_cli.set_at(obj, ["a", "b", "c"], 1)
        assert obj == {"a": {"b": {"c": 1}}}

    def test_creates_lists(self):
        obj: dict = {}
        config_cli.set_at(obj, ["xs", 0], "first")
        assert obj == {"xs": ["first"]}

    def test_replaces_value(self):
        obj = {"a": {"b": "old"}}
        config_cli.set_at(obj, ["a", "b"], "new")
        assert obj == {"a": {"b": "new"}}

    def test_merge_dicts(self):
        obj = {"a": {"b": {"x": 1}}}
        config_cli.set_at(obj, ["a", "b"], {"y": 2}, merge=True)
        assert obj == {"a": {"b": {"x": 1, "y": 2}}}

    def test_set_secret_ref(self):
        obj: dict = {}
        config_cli.set_at(obj, ["trackers", "linear", "api_key"],
                          {"source": "env", "id": "LINEAR_API_KEY"})
        assert obj["trackers"]["linear"]["api_key"]["source"] == "env"


class TestUnsetAt:
    def test_basic(self):
        obj = {"a": {"b": 1, "c": 2}}
        assert config_cli.unset_at(obj, ["a", "b"])
        assert obj == {"a": {"c": 2}}

    def test_missing_returns_false(self):
        assert config_cli.unset_at({"a": 1}, ["b"]) is False


class TestParseValue:
    def test_strict_json_required(self):
        with pytest.raises(json.JSONDecodeError):
            config_cli.parse_value("not json", strict_json=True)

    def test_lenient_falls_back_to_string(self):
        assert config_cli.parse_value("not json", strict_json=False) == "not json"

    def test_parses_obvious_json(self):
        assert config_cli.parse_value('{"a": 1}', strict_json=False) == {"a": 1}
        assert config_cli.parse_value("42", strict_json=False) == 42
        assert config_cli.parse_value("true", strict_json=False) is True


# ---------------------------------------------------------------------------
# Commands — exercise via argparse Namespaces
# ---------------------------------------------------------------------------


class _NS:
    """argparse.Namespace stand-in.

    Defaults every recognized cmd_set flag to None/False so individual
    tests only have to set the few fields they care about. Real argparse
    behaves the same way (defines every flag) so this matches production.
    """
    _SET_DEFAULTS = {
        "value": None, "strict_json": False, "merge": False, "replace": False,
        "ref_source": None, "ref_id": None, "ref_value": None,
        "ref_path": None, "ref_key": None, "ref_command": None, "ref_arg": [],
        "json": False,
    }

    def __init__(self, **kw):
        for k, v in self._SET_DEFAULTS.items():
            setattr(self, k, v)
        for k, v in kw.items():
            setattr(self, k, v)


@pytest.fixture
def cfg_path(coii_dir, monkeypatch):
    """Point COII_CONFIG_PATH at a tmp file and return that path."""
    p = coii_dir / "config.json"
    monkeypatch.setenv("COII_CONFIG_PATH", str(p))
    config._singleton = None
    return p


def _seed(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n")


class TestCmdSet:
    def test_set_string(self, cfg_path, capsys):
        _seed(cfg_path, {"version": 2, "service": {"name": "coii", "log_level": "info"}})
        rc = config_cli.cmd_set(_NS(
            path="service.log_level", value="debug",
            strict_json=False, merge=False, replace=False,
            ref_source=None, ref_id=None,
        ))
        assert rc == 0
        on_disk = json.loads(cfg_path.read_text())
        assert on_disk["service"]["log_level"] == "debug"

    def test_set_secret_ref(self, cfg_path):
        _seed(cfg_path, {"version": 2})
        rc = config_cli.cmd_set(_NS(
            path="trackers.linear.api_key", value=None,
            strict_json=False, merge=False, replace=False,
            ref_source="env", ref_id="LINEAR_API_KEY",
        ))
        assert rc == 0
        on_disk = json.loads(cfg_path.read_text())
        assert on_disk["trackers"]["linear"]["api_key"] == {
            "source": "env", "id": "LINEAR_API_KEY",
        }

    def test_strict_json_array(self, cfg_path):
        _seed(cfg_path, {"version": 2})
        rc = config_cli.cmd_set(_NS(
            path="trackers.linear.team_keys", value='["LEL","ENG"]',
            strict_json=True, merge=False, replace=False,
            ref_source=None, ref_id=None,
        ))
        assert rc == 0
        on_disk = json.loads(cfg_path.read_text())
        assert on_disk["trackers"]["linear"]["team_keys"] == ["LEL", "ENG"]

    def test_rejects_value_and_ref_together(self, cfg_path, capsys):
        _seed(cfg_path, {"version": 2})
        rc = config_cli.cmd_set(_NS(
            path="x", value="literal", ref_source="env", ref_id="FOO",
        ))
        assert rc == 2

    def test_set_secret_ref_literal(self, cfg_path):
        _seed(cfg_path, {"version": 2})
        rc = config_cli.cmd_set(_NS(
            path="x.literal", ref_source="literal", ref_value="baked-in",
        ))
        assert rc == 0
        on_disk = json.loads(cfg_path.read_text())
        assert on_disk["x"]["literal"] == {"source": "literal", "value": "baked-in"}

    def test_set_secret_ref_file(self, cfg_path):
        _seed(cfg_path, {"version": 2})
        rc = config_cli.cmd_set(_NS(
            path="trackers.linear.api_key",
            ref_source="file", ref_path="/etc/coii/secrets.json",
            ref_key="linear.api_key",
        ))
        assert rc == 0
        on_disk = json.loads(cfg_path.read_text())
        assert on_disk["trackers"]["linear"]["api_key"] == {
            "source": "file", "path": "/etc/coii/secrets.json",
            "key": "linear.api_key",
        }

    def test_set_secret_ref_file_no_key(self, cfg_path):
        _seed(cfg_path, {"version": 2})
        rc = config_cli.cmd_set(_NS(
            path="x.f", ref_source="file", ref_path="/tmp/raw.txt",
        ))
        assert rc == 0
        on_disk = json.loads(cfg_path.read_text())
        assert on_disk["x"]["f"] == {"source": "file", "path": "/tmp/raw.txt"}

    def test_set_secret_ref_exec(self, cfg_path):
        _seed(cfg_path, {"version": 2})
        rc = config_cli.cmd_set(_NS(
            path="trackers.linear.api_key",
            ref_source="exec", ref_command="/usr/bin/op",
            ref_arg=["read", "op://Personal/Linear/api"],
        ))
        assert rc == 0
        on_disk = json.loads(cfg_path.read_text())
        assert on_disk["trackers"]["linear"]["api_key"] == {
            "source": "exec", "command": "/usr/bin/op",
            "args": ["read", "op://Personal/Linear/api"],
        }

    def test_file_source_requires_path(self, cfg_path):
        _seed(cfg_path, {"version": 2})
        rc = config_cli.cmd_set(_NS(path="x", ref_source="file"))
        assert rc == 2

    def test_exec_source_requires_command(self, cfg_path):
        _seed(cfg_path, {"version": 2})
        rc = config_cli.cmd_set(_NS(path="x", ref_source="exec"))
        assert rc == 2

    def test_literal_source_requires_value(self, cfg_path):
        _seed(cfg_path, {"version": 2})
        rc = config_cli.cmd_set(_NS(path="x", ref_source="literal"))
        assert rc == 2


class TestCmdGet:
    def test_existing_path(self, cfg_path, capsys):
        _seed(cfg_path, {"service": {"name": "coii"}})
        rc = config_cli.cmd_get(_NS(path="service.name", json=False))
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert out == "coii"

    def test_missing_path(self, cfg_path):
        _seed(cfg_path, {"service": {}})
        rc = config_cli.cmd_get(_NS(path="service.name", json=False))
        assert rc == 1

    def test_json_output(self, cfg_path, capsys):
        _seed(cfg_path, {"trackers": {"linear": {"team_keys": ["A", "B"]}}})
        rc = config_cli.cmd_get(_NS(path="trackers.linear.team_keys", json=True))
        out = capsys.readouterr().out
        assert rc == 0
        assert json.loads(out) == ["A", "B"]


class TestCmdUnset:
    def test_basic(self, cfg_path):
        _seed(cfg_path, {"a": {"b": 1, "c": 2}})
        rc = config_cli.cmd_unset(_NS(path="a.b"))
        assert rc == 0
        assert json.loads(cfg_path.read_text()) == {"a": {"c": 2}}

    def test_missing(self, cfg_path):
        _seed(cfg_path, {"a": {}})
        rc = config_cli.cmd_unset(_NS(path="a.b"))
        assert rc == 1


class TestCmdFile:
    def test_prints_path(self, cfg_path, capsys):
        rc = config_cli.cmd_file(_NS())
        assert rc == 0
        assert str(cfg_path) in capsys.readouterr().out


class TestCmdValidate:
    def test_valid(self, cfg_path, capsys):
        _seed(cfg_path, {"version": 2, "service": {"name": "coii", "log_level": "info"}})
        rc = config_cli.cmd_validate(_NS(json=False))
        assert rc == 0
        assert "ok" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class TestAuditConfig:
    """Pure-function audit: categorize secret slots."""

    def test_clean(self, monkeypatch):
        monkeypatch.setenv("LINEAR_API_KEY", "lin")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ant")
        report = config_cli.audit_config({
            "trackers": {"linear": {
                "api_key": {"source": "env", "id": "LINEAR_API_KEY"},
            }},
            "models": {"providers": {
                "anthropic": {"api_key": {"source": "env", "id": "ANTHROPIC_API_KEY"}},
            }},
        })
        assert report["plaintext"] == []
        assert report["unresolved"] == []
        assert sorted(report["ok"]) == [
            "models.providers.anthropic.api_key",
            "trackers.linear.api_key",
        ]

    def test_flags_literal_string_in_secret_slot(self, monkeypatch):
        report = config_cli.audit_config({
            "trackers": {"linear": {"api_key": "sk-baked-in"}},
        })
        assert report["plaintext"] == ["trackers.linear.api_key"]

    def test_flags_explicit_literal_ref(self, monkeypatch):
        report = config_cli.audit_config({
            "trackers": {"linear": {"webhook_secret": {
                "source": "literal", "value": "leaked",
            }}},
        })
        assert report["plaintext"] == ["trackers.linear.webhook_secret"]

    def test_flags_unresolved_env_ref(self, monkeypatch):
        monkeypatch.delenv("MISSING_KEY", raising=False)
        report = config_cli.audit_config({
            "trackers": {"linear": {"api_key": {
                "source": "env", "id": "MISSING_KEY",
            }}},
        })
        assert report["unresolved"] == ["trackers.linear.api_key"]
        assert report["plaintext"] == []

    def test_skips_empty_and_null(self):
        report = config_cli.audit_config({
            "trackers": {"linear": {"api_key": None, "webhook_secret": ""}},
        })
        assert report["plaintext"] == []
        assert report["unresolved"] == []
        assert report["ok"] == []

    def test_secrets_container_not_flagged(self):
        # `secrets` is openclaw's container for provider configs — its name
        # matches the heuristic regex but the value is a sub-tree, not a leaf.
        # Auditing must not flag it as plaintext.
        report = config_cli.audit_config({
            "secrets": {"providers": {"default": {"source": "env"}}},
        })
        assert report["plaintext"] == []
        assert report["unresolved"] == []
        assert report["ok"] == []

    def test_walks_nested_provider_map(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
        report = config_cli.audit_config({
            "models": {"providers": {
                "openai": {"api_key": {"source": "env", "id": "OPENAI_API_KEY"}},
                "anthropic": {"api_key": {"source": "env", "id": "ANTHROPIC_API_KEY"}},
            }},
        })
        assert report["unresolved"] == ["models.providers.openai.api_key"]
        assert report["ok"] == ["models.providers.anthropic.api_key"]


class TestCmdAudit:
    def test_clean_returns_zero(self, cfg_path, monkeypatch):
        monkeypatch.setenv("LINEAR_API_KEY", "lin")
        _seed(cfg_path, {
            "version": 2,
            "trackers": {"linear": {
                "api_key": {"source": "env", "id": "LINEAR_API_KEY"},
            }},
        })
        assert config_cli.cmd_audit(_NS(json=False)) == 0

    def test_plaintext_returns_one(self, cfg_path, capsys):
        _seed(cfg_path, {
            "version": 2,
            "trackers": {"linear": {"api_key": "literal-key"}},
        })
        rc = config_cli.cmd_audit(_NS(json=False))
        assert rc == 1
        assert "PLAINTEXT" in capsys.readouterr().out

    def test_unresolved_returns_two(self, cfg_path, monkeypatch, capsys):
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        _seed(cfg_path, {
            "version": 2,
            "trackers": {"linear": {
                "api_key": {"source": "env", "id": "LINEAR_API_KEY"},
            }},
        })
        rc = config_cli.cmd_audit(_NS(json=False))
        assert rc == 2
        assert "UNRESOLVED" in capsys.readouterr().out

    def test_unresolved_outranks_plaintext(self, cfg_path, monkeypatch):
        monkeypatch.delenv("MISSING", raising=False)
        _seed(cfg_path, {
            "version": 2,
            "trackers": {"linear": {
                "api_key": "literal",
                "webhook_secret": {"source": "env", "id": "MISSING"},
            }},
        })
        # Both findings present; unresolved rc=2 must win.
        assert config_cli.cmd_audit(_NS(json=False)) == 2

    def test_json_output(self, cfg_path, monkeypatch, capsys):
        monkeypatch.delenv("MISSING", raising=False)
        _seed(cfg_path, {
            "version": 2,
            "trackers": {"linear": {
                "api_key": {"source": "env", "id": "MISSING"},
            }},
        })
        config_cli.cmd_audit(_NS(json=True))
        out = capsys.readouterr().out
        report = json.loads(out)
        assert report["unresolved"] == ["trackers.linear.api_key"]
        assert report["plaintext"] == []
