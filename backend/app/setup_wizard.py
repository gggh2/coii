"""Interactive setup wizard — `coii setup --wizard`.

Walks the user through:

  1. LLM provider + key + model spec → ``models.default`` in config.json
     plus the actual API key in the env file.
  2. Linear API key + team key → secret in env file,
     ``trackers.linear.team_keys`` + structured settings in config.json.
  3. Service log level → ``service.log_level`` in config.json.
  4. Seeds ``~/.coii/`` from packaged defaults (skip-if-exists).

After this the runtime is fully configured: ``coii serve`` will pick up
the polling job and route Linear events without any further env tweaks.

Webhook delivery is supported by the runtime (see ``api/webhooks``) but
not surfaced here — most users start on polling and only graduate to
webhooks when they need lower latency. Set ``LINEAR_WEBHOOK_SECRET`` by
hand if you want it.

Files written
-------------
* ``services/coii/.env.local_deploy`` — provider + Linear API keys, signing
  secret. Mode 0600. Repository-local; gitignored.
* ``~/.coii/config.json`` — structured config (model default, team keys,
  poll interval, log level). SecretRefs point at the env-var names above.

Pattern: pure render/parse helpers live above the ``main()`` shell so
tests can exercise them without stdin tricks.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from app import config, config_cli
from app.cli import _seed
from app.util import coii_root, defaults_root


# ---------------------------------------------------------------------------
# Pure helpers (testable without interactive I/O).
# ---------------------------------------------------------------------------

# Only true secrets live in the env file from now on. Structured config
# (team keys, log level, model spec) goes into ~/.coii/config.json.
ENV_KEYS = (
    "LINEAR_API_KEY",
    "LINEAR_WEBHOOK_SECRET",
    "LINEAR_TEAM_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)


def parse_env_file(text: str) -> dict[str, str]:
    """Parse a dotenv-style text into a dict.

    Lenient: ignores blank lines, comments, and lines without ``=``.
    Keeps the *last* occurrence of any key (matches dotenv semantics).
    Strips a single layer of surrounding quotes from the value.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        out[key] = val
    return out


def render_env_file(values: dict[str, str]) -> str:
    """Render an ordered, sectioned .env file. Empty values become bare ``KEY=``."""
    sections: list[tuple[str, tuple[str, ...]]] = [
        ("# Linear (tracker)", (
            "LINEAR_API_KEY",
            "LINEAR_WEBHOOK_SECRET",
            "LINEAR_TEAM_KEY",
        )),
        ("# LLM provider keys (referenced by SecretRef in config.json)",
         ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")),
    ]
    out: list[str] = []
    seen: set[str] = set()
    for header, keys in sections:
        out.append(header)
        for k in keys:
            out.append(f"{k}={values.get(k, '')}")
            seen.add(k)
        out.append("")
    extras = sorted(k for k in values if k not in seen)
    if extras:
        out.append("# (extra keys preserved from existing file)")
        for k in extras:
            out.append(f"{k}={values[k]}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def merge_env(existing: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """Merge ``new`` over ``existing``; only non-empty new values win."""
    out = dict(existing)
    for k, v in new.items():
        if v != "" and v is not None:
            out[k] = v
    return out


def generate_webhook_secret() -> str:
    """64-char hex secret. Linear's UI accepts arbitrary string secrets."""
    return secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Provider definitions — registry of what we know how to ask about.
# Adding a new provider = one entry here + an LLMProvider impl.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderChoice:
    name: str
    label: str
    env_key: str
    default_model: str
    help_url: str


PROVIDER_CHOICES: tuple[ProviderChoice, ...] = (
    ProviderChoice(
        name="anthropic",
        label="Anthropic (Claude)",
        env_key="ANTHROPIC_API_KEY",
        default_model="anthropic/claude-sonnet-4-6",
        help_url="https://console.anthropic.com/settings/keys",
    ),
    ProviderChoice(
        name="openai",
        label="OpenAI (GPT)",
        env_key="OPENAI_API_KEY",
        default_model="openai/gpt-4o",
        help_url="https://platform.openai.com/api-keys",
    ),
)


def find_provider(name: str) -> ProviderChoice | None:
    return next((p for p in PROVIDER_CHOICES if p.name == name), None)


# ---------------------------------------------------------------------------
# Config writer — translates wizard answers into config.json mutations.
# ---------------------------------------------------------------------------


def apply_to_config(
    raw_cfg: dict,
    *,
    log_level: str | None = None,
    model_spec: str | None = None,
    team_keys: tuple[str, ...] | None = None,
    poll_interval_seconds: int | None = None,
) -> dict:
    """Apply non-secret wizard answers to a raw config dict (in place).

    Pure function so the test suite can exercise it without writing
    files. Only fields the user explicitly answered are touched —
    everything else stays as-is so re-running the wizard preserves
    user edits.
    """
    if log_level:
        config_cli.set_at(raw_cfg, ["service", "log_level"], log_level)
    if model_spec:
        config_cli.set_at(raw_cfg, ["models", "default"], model_spec)
    if team_keys is not None:
        config_cli.set_at(raw_cfg, ["trackers", "linear", "team_keys"], list(team_keys))
    if poll_interval_seconds:
        config_cli.set_at(
            raw_cfg, ["trackers", "linear", "poll_interval_seconds"],
            poll_interval_seconds,
        )
    return raw_cfg


# ---------------------------------------------------------------------------
# Interactive shell — thin wrapper around the helpers above.
# ---------------------------------------------------------------------------

# When running from a dev checkout, secrets go into the repo-local
# `services/coii/.env.local_deploy` (next to the code). When installed
# via `uv tool install`, the path two-parents-up lands inside the tool
# venv — useless — so fall back to `~/.coii/.env`. Detection: dev
# checkouts have a `pyproject.toml` next to the supposed env file.
SERVICE_ROOT = Path(__file__).resolve().parents[2]
if (SERVICE_ROOT / "pyproject.toml").exists() or (SERVICE_ROOT / ".env.local_deploy").exists():
    ENV_FILE = SERVICE_ROOT / ".env.local_deploy"
else:
    ENV_FILE = coii_root() / ".env"


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw or default


def _ask_secret(prompt: str) -> str:
    return getpass.getpass(f"{prompt} (input hidden): ").strip()


def _print_header(title: str) -> None:
    print()
    print(f"── {title} " + "─" * max(0, 60 - len(title)))


def _existing_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    return parse_env_file(ENV_FILE.read_text(encoding="utf-8"))


def _write_env(values: dict[str, str]) -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(render_env_file(values), encoding="utf-8")
    os.chmod(ENV_FILE, 0o600)
    print(f"  wrote {ENV_FILE} (mode 600)")


def _read_raw_config() -> dict:
    """Read the active config or return the packaged defaults if missing."""
    path = config.config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    defaults = (Path(__file__).parent / "default" / "config.json").resolve()
    if defaults.exists():
        return json.loads(defaults.read_text(encoding="utf-8"))
    return {"version": config.CONFIG_VERSION}


def _write_raw_config(raw: dict) -> Path:
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return path


_TEAM_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,9}$")


def _ask_team_key(default: str) -> str:
    """Prompt for a Linear team key. Empty input is allowed (returns "")."""
    while True:
        raw = _ask("Linear team key (uppercase, e.g. ENG, DEMO) — leave blank to skip", default).upper()
        if not raw:
            return ""
        if _TEAM_KEY_RE.match(raw):
            return raw
        print("  must be 2-10 uppercase letters/digits — what Linear shows in ticket IDs (ENG-42 → ENG)")


def _pick_provider() -> ProviderChoice | None:
    print("Pick an LLM provider for the API runtime:")
    for i, p in enumerate(PROVIDER_CHOICES, start=1):
        print(f"  {i}) {p.label}")
    print(f"  {len(PROVIDER_CHOICES) + 1}) Skip — use the local Claude Code CLI only")
    while True:
        raw = input(f"Choice [1-{len(PROVIDER_CHOICES) + 1}]: ").strip()
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(PROVIDER_CHOICES):
                return PROVIDER_CHOICES[n - 1]
            if n == len(PROVIDER_CHOICES) + 1:
                return None
        print("  invalid, try again")


def _collect_interactive(
    existing: dict[str, str], raw_cfg: dict,
) -> tuple[dict[str, str], dict, str]:
    """Return ``(new_env, cfg_updates, team_key)`` from interactive prompts."""
    new_env: dict[str, str] = {}
    cfg_updates: dict = {}

    _print_header("LLM provider")
    provider = _pick_provider()
    if provider is None:
        print("  ok — leaving model+keys blank.")
        print("  the runtime will fall back to the local `claude` CLI if it's installed.")
    else:
        print(f"  get a key here: {provider.help_url}")
        existing_key = existing.get(provider.env_key, "")
        existing_hint = f" [keep existing {provider.env_key[:6]}…]" if existing_key else ""
        key = _ask_secret(f"Paste {provider.env_key}{existing_hint}")
        if key:
            new_env[provider.env_key] = key
        elif not existing_key:
            print(f"  no key provided — {provider.env_key} stays blank")
        existing_default = (raw_cfg.get("models") or {}).get("default") or provider.default_model
        cfg_updates["model_spec"] = _ask("Default model spec", default=existing_default)

    _print_header("Linear (tracker)")
    print("  Need a Linear *personal* API token (NOT an OAuth client / workspace key).")
    print("  How to create one:")
    print("    1. Open https://linear.app/settings/api")
    print("    2. Click 'New API key' under the 'Personal API keys' section")
    print("    3. Name it (e.g. 'coii'), copy the token — starts with 'lin_api_…'")
    print("  Required scopes: read + write on issues + comments for the team(s)")
    print("  you want the agent to see.")
    existing_key = existing.get("LINEAR_API_KEY", "")
    existing_hint = " [keep existing]" if existing_key else ""
    key = _ask_secret(f"Paste LINEAR_API_KEY{existing_hint}")
    if key:
        new_env["LINEAR_API_KEY"] = key

    existing_team = existing.get("LINEAR_TEAM_KEY", "")
    if not existing_team:
        existing_arr = (raw_cfg.get("trackers") or {}).get("linear", {}).get("team_keys") or []
        if existing_arr:
            existing_team = str(existing_arr[0])
    team_key = _ask_team_key(default=existing_team)
    if team_key:
        new_env["LINEAR_TEAM_KEY"] = team_key
        cfg_updates["team_keys"] = (team_key,)
    else:
        print("  ok — skipping team key. Polling stays disabled until you set")
        print("  trackers.linear.team_keys later via `coii config set`.")

    return new_env, cfg_updates, team_key


def _collect_non_interactive(
    existing: dict[str, str], raw_cfg: dict,
) -> tuple[dict[str, str], dict, str]:
    """Read wizard answers from env vars instead of prompts.

    Inputs (env-driven):

      ``COII_WIZARD_PROVIDER``     anthropic | openai | skip   (default: skip)
      ``COII_WIZARD_API_KEY``      provider API key            (required if provider != skip)
      ``COII_WIZARD_MODEL``        model spec                  (default: provider's default)
      ``LINEAR_API_KEY``           Linear personal token        (required)
      ``LINEAR_TEAM_KEY``          team short-code              (optional — polling disabled if blank)
      ``LINEAR_WEBHOOK_SECRET``    signing secret               (optional — only written if set)
      ``COII_WIZARD_LOG_LEVEL``    debug | info | warning       (optional — only written if set)
    """
    new_env: dict[str, str] = {}
    cfg_updates: dict = {}

    provider_name = (os.getenv("COII_WIZARD_PROVIDER") or "skip").lower()
    if provider_name not in ("anthropic", "openai", "skip"):
        raise SystemExit(f"COII_WIZARD_PROVIDER must be anthropic|openai|skip, got {provider_name!r}")
    if provider_name != "skip":
        provider = find_provider(provider_name)
        assert provider is not None  # narrow for type-checker
        api_key = os.getenv("COII_WIZARD_API_KEY") or ""
        if not api_key:
            raise SystemExit("COII_WIZARD_API_KEY required when COII_WIZARD_PROVIDER is set")
        new_env[provider.env_key] = api_key
        cfg_updates["model_spec"] = os.getenv("COII_WIZARD_MODEL") or provider.default_model

    linear_key = os.getenv("LINEAR_API_KEY") or ""
    if not linear_key:
        raise SystemExit("LINEAR_API_KEY required for non-interactive setup")
    new_env["LINEAR_API_KEY"] = linear_key

    team_key = (os.getenv("LINEAR_TEAM_KEY") or "").upper()
    if team_key:
        if not _TEAM_KEY_RE.match(team_key):
            raise SystemExit(f"LINEAR_TEAM_KEY must be 2-10 uppercase chars, got {team_key!r}")
        new_env["LINEAR_TEAM_KEY"] = team_key
        cfg_updates["team_keys"] = (team_key,)

    webhook_secret = os.getenv("LINEAR_WEBHOOK_SECRET") or ""
    if webhook_secret:
        new_env["LINEAR_WEBHOOK_SECRET"] = webhook_secret

    log_level = (os.getenv("COII_WIZARD_LOG_LEVEL") or "").lower()
    if log_level:
        cfg_updates["log_level"] = log_level
    return new_env, cfg_updates, team_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Setup wizard for coii.")
    parser.add_argument(
        "--non-interactive", action="store_true",
        help="Read answers from COII_WIZARD_* + LINEAR_* env vars instead of prompts.",
    )
    args = parser.parse_args(argv)

    print("coii setup --wizard" + (" --non-interactive" if args.non_interactive else ""))
    print(f"  service root: {SERVICE_ROOT}")
    print(f"  env file:     {ENV_FILE}")
    print(f"  coii root:    {coii_root()}")
    print(f"  config:       {config.config_path()}")

    existing = _existing_env()
    raw_cfg = _read_raw_config()
    if existing and not args.non_interactive:
        print(f"\nFound existing {ENV_FILE.name} with {len(existing)} keys.")
        print("Press <enter> at any prompt to keep the existing value.")

    if args.non_interactive:
        new_env, cfg_updates, team_key = _collect_non_interactive(existing, raw_cfg)
    else:
        new_env, cfg_updates, team_key = _collect_interactive(existing, raw_cfg)

    _print_header("Writing config")
    merged = merge_env(existing, new_env)
    _write_env(merged)

    apply_to_config(raw_cfg, **cfg_updates)
    cfg_path = _write_raw_config(raw_cfg)
    print(f"  wrote {cfg_path}")

    dst = coii_root()
    dst.mkdir(parents=True, exist_ok=True)
    copied, skipped = _seed(defaults_root(), dst)
    print(f"  seeded {dst}: {copied} new, {skipped} preserved")

    _print_header("Next steps")
    print("  1. coii serve")
    if team_key:
        print(f"     (polling auto-starts: trackers.linear.team_keys=[{team_key!r}])")
    else:
        print("     (no team key set — polling stays disabled. To enable later:")
        print("      coii config set trackers.linear.team_keys '[\"ENG\"]')")
    print("  2. In Linear, create a ticket with the `agent:coder` label —")
    print("     the poller picks it up on the next interval and the agent replies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
