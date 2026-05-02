"""Config loader — single source of truth for runtime configuration.

Mirrors openclaw's pattern: structured config in JSON, secrets in env files,
JSON references env vars via SecretRef shapes.

Files
-----
* ``~/.coii/config.json`` — structured config (this module's primary input).
* ``services/coii/.env.local_deploy`` — repo-local secrets (when running from
  a clone).
* ``~/.coii/.env`` — daemon-mode secrets (loaded for installed deployments).

Env precedence (highest -> lowest), applied at ``load()`` time:

  1. process env (anything already in ``os.environ`` wins)
  2. ``./.env.local_deploy`` from the repo root
  3. ``~/.coii/.env``
  4. ``config.json`` ``env`` block

Direct config keys (e.g. ``trackers.linear.api_key``) are SecretRef shapes
that resolve through the chain above.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.util import coii_root

log = logging.getLogger(__name__)

CONFIG_VERSION = 2

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def repo_env_path() -> Path | None:
    """Repo-local ``services/coii/.env.local_deploy`` if dotenv loading is enabled.

    Returns ``None`` when ``COII_DISABLE_DOTENV=1`` (used by tests so the
    developer's real keys don't leak into the test environment).
    """
    if os.getenv("COII_DISABLE_DOTENV") == "1":
        return None
    # services/coii/backend/app/config.py → services/coii/.env.local_deploy
    return Path(__file__).resolve().parents[2] / ".env.local_deploy"


def config_path() -> Path:
    """Active config file path. Override via ``COII_CONFIG_PATH``."""
    raw = os.getenv("COII_CONFIG_PATH")
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return coii_root() / "config.json"


def home_env_path() -> Path | None:
    """``~/.coii/.env`` if dotenv loading is enabled, else ``None``."""
    if os.getenv("COII_DISABLE_DOTENV") == "1":
        return None
    return coii_root() / ".env"


# ---------------------------------------------------------------------------
# SecretRef
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecretRef:
    """A reference to a secret value, never the value itself.

    ``source`` is one of:
      - ``"env"``      — read ``os.environ[id]``
      - ``"literal"``  — value baked into config (use sparingly; ``audit`` flags it)
      - ``"exec"``     — run ``command args...`` and trim stdout
      - ``"file"``     — read ``path`` (optionally ``key`` for JSON deref)
    """
    source: str
    id: str | None = None
    value: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    path: str | None = None
    key: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"source": self.source}
        if self.id is not None:
            out["id"] = self.id
        if self.value is not None:
            out["value"] = self.value
        if self.command is not None:
            out["command"] = self.command
        if self.args:
            out["args"] = list(self.args)
        if self.path is not None:
            out["path"] = self.path
        if self.key is not None:
            out["key"] = self.key
        return out


def parse_ref(raw: Any) -> SecretRef | None:
    """Normalize a JSON value into a SecretRef.

    Accepts:
      - ``None`` / ``""``        → returns ``None`` (no ref)
      - ``{"source": "env", "id": "FOO"}``  → structured ref
      - non-empty string         → treated as a literal value (legacy form)
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        # Legacy/literal: a bare string in the config is a baked-in value.
        # Discouraged but tolerated for backward compatibility.
        return SecretRef(source="literal", value=raw)
    if not isinstance(raw, dict):
        log.warning("invalid SecretRef shape: %r", raw)
        return None

    source = str(raw.get("source") or "").lower()
    if source not in ("env", "literal", "exec", "file"):
        log.warning("unknown SecretRef source %r — ignoring", source)
        return None

    args_raw = raw.get("args") or ()
    if isinstance(args_raw, list):
        args = tuple(str(a) for a in args_raw)
    else:
        args = ()

    return SecretRef(
        source=source,
        id=raw.get("id"),
        value=raw.get("value"),
        command=raw.get("command"),
        args=args,
        path=raw.get("path"),
        key=raw.get("key"),
    )


def resolve_ref(ref: SecretRef | None) -> str | None:
    """Return the plaintext value for a ref, or ``None`` if unresolved."""
    if ref is None:
        return None
    if ref.source == "env":
        if not ref.id:
            return None
        v = os.getenv(ref.id)
        return v if v else None
    if ref.source == "literal":
        return ref.value or None
    if ref.source == "file":
        if not ref.path:
            return None
        try:
            text = Path(os.path.expanduser(ref.path)).read_text(encoding="utf-8")
        except OSError as e:
            log.warning("SecretRef file %s unreadable: %s", ref.path, e)
            return None
        if not ref.key:
            return text.strip() or None
        try:
            obj: Any = json.loads(text)
        except json.JSONDecodeError as e:
            log.warning("SecretRef file %s not JSON: %s", ref.path, e)
            return None
        for part in ref.key.split("."):
            if not isinstance(obj, dict) or part not in obj:
                return None
            obj = obj[part]
        return str(obj) if obj is not None else None
    if ref.source == "exec":
        if not ref.command:
            return None
        try:
            out = subprocess.run(
                [ref.command, *ref.args],
                capture_output=True, text=True, timeout=10, check=True,
            )
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("SecretRef exec %s failed: %s", ref.command, e)
            return None
        return out.stdout.strip() or None
    return None


# ---------------------------------------------------------------------------
# Typed views
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServiceConfig:
    name: str = "coii"
    log_level: str = "info"


@dataclass(frozen=True)
class LinearConfig:
    enabled: bool = True
    api_key_ref: SecretRef | None = None
    webhook_secret_ref: SecretRef | None = None
    team_keys: tuple[str, ...] = ()
    poll_interval_seconds: int = 30

    @property
    def api_key(self) -> str:
        return resolve_ref(self.api_key_ref) or ""

    @property
    def webhook_secret(self) -> str:
        return resolve_ref(self.webhook_secret_ref) or ""


@dataclass(frozen=True)
class ProviderConfig:
    type: str
    api_key_ref: SecretRef | None = None
    # Optional override for the SDK's default endpoint — useful when the
    # user's key targets a proxy / regional gateway / OpenAI-compatible
    # server (DeepSeek, Together, vLLM, Ollama, …). Empty means "use the
    # SDK default", which itself falls through to the SDK's own env var
    # (ANTHROPIC_BASE_URL / OPENAI_BASE_URL).
    base_url: str | None = None

    @property
    def api_key(self) -> str | None:
        return resolve_ref(self.api_key_ref)


@dataclass(frozen=True)
class ModelsConfig:
    default: str = "anthropic/claude-sonnet-4-6"
    providers: dict[str, ProviderConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeConfig:
    type: str = "claude_code"
    command: str | None = "claude"


@dataclass
class Config:
    version: int
    service: ServiceConfig
    linear: LinearConfig
    models: ModelsConfig
    runtimes: dict[str, RuntimeConfig]
    memory: dict[str, Any]
    raw: dict[str, Any]


# ---------------------------------------------------------------------------
# Load / migrate
# ---------------------------------------------------------------------------


def _apply_env_chain(raw_config: dict[str, Any]) -> None:
    """Populate ``os.environ`` from the .env chain + config.env block.

    Existing process-env values are never overwritten. Order of fallbacks
    (each lower step only fills missing keys):

      1. process env (already set)
      2. services/coii/.env.local_deploy
      3. ~/.coii/.env
      4. config.json's `env` block
    """
    repo_env = repo_env_path()
    if repo_env and repo_env.exists():
        load_dotenv(repo_env, override=False)
    home_env = home_env_path()
    if home_env and home_env.exists():
        load_dotenv(home_env, override=False)
    for k, v in (raw_config.get("env") or {}).items():
        if k not in os.environ and v not in (None, ""):
            os.environ[k] = str(v)


def _build_typed(raw: dict[str, Any]) -> Config:
    svc = raw.get("service") or {}
    service = ServiceConfig(
        name=str(svc.get("name", "coii")),
        log_level=str(svc.get("log_level", "info")),
    )

    linear_raw = (raw.get("trackers") or {}).get("linear") or {}
    linear = LinearConfig(
        enabled=bool(linear_raw.get("enabled", True)),
        api_key_ref=parse_ref(linear_raw.get("api_key")),
        webhook_secret_ref=parse_ref(linear_raw.get("webhook_secret")),
        team_keys=tuple(
            str(k).upper() for k in (linear_raw.get("team_keys") or []) if k
        ),
        poll_interval_seconds=int(linear_raw.get("poll_interval_seconds") or 30),
    )

    models_raw = raw.get("models") or {}
    providers: dict[str, ProviderConfig] = {}
    for name, cfg in (models_raw.get("providers") or {}).items():
        providers[name] = ProviderConfig(
            type=str(cfg.get("type", name)),
            api_key_ref=parse_ref(cfg.get("api_key")),
            base_url=(str(cfg["base_url"]).strip() or None) if cfg.get("base_url") else None,
        )
    models = ModelsConfig(
        default=str(models_raw.get("default", "anthropic/claude-sonnet-4-6")),
        providers=providers,
    )

    runtimes: dict[str, RuntimeConfig] = {}
    for name, cfg in (raw.get("runtimes") or {}).items():
        runtimes[name] = RuntimeConfig(
            type=str(cfg.get("type", "claude_code")),
            command=cfg.get("command"),
        )
    if "default" not in runtimes:
        runtimes["default"] = RuntimeConfig()

    return Config(
        version=_read_version(raw),
        service=service,
        linear=linear,
        models=models,
        runtimes=runtimes,
        memory=raw.get("memory") or {},
        raw=raw,
    )


def _read_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error("config.json malformed at %s: %s", path, e)
        return {}


# ---------------------------------------------------------------------------
# Migrations
#
# Forward-only. Each entry migrates v[k] → v[k+1]. Applied at load time and
# the upgraded shape is written back so we don't re-migrate every load.
# Rollback is not supported; the install layer pins the binary version
# (`COII_REF=<tag> bash install.sh`) but config moves forward only.
#
# To ship a v3:
#   1. Bump CONFIG_VERSION = 3.
#   2. Write `def _migrate_v2_to_v3(raw): ... return raw`.
#   3. Register: MIGRATIONS[2] = _migrate_v2_to_v3.
# ---------------------------------------------------------------------------

from typing import Callable  # noqa: E402

MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _read_version(raw: dict[str, Any]) -> int:
    """Read raw["version"] as an int. Missing field → CONFIG_VERSION (a
    fresh empty config is treated as already-current). Explicit 0 / 1 /
    any sub-current int triggers migration; non-numeric raises."""
    if "version" not in raw:
        return CONFIG_VERSION
    return int(raw["version"])


def _migrate(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Apply pending forward migrations. Returns (raw, changed)."""
    changed = False
    while True:
        v = _read_version(raw)
        if v >= CONFIG_VERSION:
            return raw, changed
        fn = MIGRATIONS.get(v)
        if fn is None:
            raise RuntimeError(
                f"config v{v} has no registered migration to v{v + 1}. "
                f"upgrade coii through the missing version first, or delete "
                f"{config_path()} and re-run `coii setup --wizard`."
            )
        raw = fn(raw)
        raw["version"] = v + 1
        log.info("config migrated v%d → v%d", v, v + 1)
        changed = True


def load(path: Path | None = None) -> Config:
    """Read, migrate-if-needed, env-chain, and return a typed Config.

    Idempotent — safe to call from tests with isolated paths. Missing or
    malformed config files yield a Config built from each dataclass's
    field defaults. If migrations ran, the upgraded shape is persisted
    back to disk on a best-effort basis (read-only filesystems just keep
    the in-memory upgrade for the rest of the process).
    """
    cfg_path = path or config_path()
    raw = _read_raw(cfg_path)
    raw, migrated = _migrate(raw)
    if migrated and cfg_path.exists():
        try:
            cfg_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        except OSError as e:
            log.warning("could not persist upgraded config to %s: %s", cfg_path, e)
    _apply_env_chain(raw)
    return _build_typed(raw)


# Singleton — most callers want one shared Config per process.
_singleton: Config | None = None


def get() -> Config:
    global _singleton
    if _singleton is None:
        _singleton = load()
    return _singleton


def reload() -> Config:
    """Re-read config + env files. Used by tests and ``coii config`` mutations."""
    global _singleton
    _singleton = load()
    return _singleton


__all__ = [
    "CONFIG_VERSION",
    "Config",
    "LinearConfig",
    "ModelsConfig",
    "ProviderConfig",
    "RuntimeConfig",
    "SecretRef",
    "ServiceConfig",
    "config_path",
    "get",
    "home_env_path",
    "load",
    "parse_ref",
    "reload",
    "resolve_ref",
]
