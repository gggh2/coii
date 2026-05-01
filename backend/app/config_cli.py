"""``coii config`` subcommands — non-interactive editing of config.json.

Mirrors the relevant subset of openclaw's ``openclaw config`` surface:

  coii config file
  coii config get <path>      [--json]
  coii config set <path> <value>  [--strict-json] [--merge|--replace]
  coii config set <path> --ref-source env --ref-id <NAME>
  coii config unset <path>
  coii config validate
  coii config audit           [--json]

Paths use dot + bracket notation: ``trackers.linear.api_key``,
``agents.list[0].id``. Values that look like JSON are parsed as JSON;
``--strict-json`` requires it.

Out of scope here (deliberately): schema generation, batch/patch from
file, provider builder mode, exec/file SecretRef builders. Add when
needed; the current shape is a one-screen surface that covers the
wizard's needs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from app import config

_BRACKET_RE = re.compile(r"^([^\[]+)((?:\[\d+\])*)$")


def split_path(path: str) -> list[str | int]:
    """Split ``a.b[0].c`` into ``['a', 'b', 0, 'c']``.

    Raises ValueError on an unparseable segment so the CLI surfaces a
    sensible error instead of silently navigating past garbage.
    """
    out: list[str | int] = []
    for seg in path.split("."):
        m = _BRACKET_RE.match(seg.strip())
        if not m or not m.group(1):
            raise ValueError(f"invalid path segment: {seg!r}")
        out.append(m.group(1))
        for idx in re.findall(r"\[(\d+)\]", m.group(2) or ""):
            out.append(int(idx))
    return out


def get_at(obj: Any, parts: list[str | int]) -> Any:
    cur = obj
    for p in parts:
        if isinstance(p, int):
            if not isinstance(cur, list) or p >= len(cur):
                return None
            cur = cur[p]
        else:
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
    return cur


def _ensure_container(parent: Any, key: str | int, next_key: str | int) -> Any:
    """Return container at parent[key], creating it if missing.

    Type of created container is inferred from ``next_key``: int → list,
    str → dict.
    """
    new_container: Any = [] if isinstance(next_key, int) else {}
    if isinstance(parent, dict):
        existing = parent.get(key)
        if existing is None or not isinstance(existing, (dict, list)):
            parent[key] = new_container
        return parent[key]
    # list parent
    while len(parent) <= key:  # type: ignore[operator,arg-type]
        parent.append(None)
    if parent[key] is None or not isinstance(parent[key], (dict, list)):
        parent[key] = new_container
    return parent[key]


def set_at(
    obj: dict, parts: list[str | int], value: Any,
    *, merge: bool = False, replace: bool = False,
) -> None:
    """Set ``obj`` at ``parts`` to ``value``.

    ``merge=True`` deep-merges dicts (useful for protected map paths).
    ``replace=True`` is a no-op marker for parity with openclaw's flag —
    plain set already replaces, so we just keep the flag for symmetry.
    """
    if not parts:
        raise ValueError("empty path")
    cur: Any = obj
    for i, p in enumerate(parts[:-1]):
        cur = _ensure_container(cur, p, parts[i + 1])
    last = parts[-1]
    if merge and isinstance(value, dict) and isinstance(cur, dict):
        existing = cur.get(last)
        if isinstance(existing, dict):
            cur[last] = _deep_merge(existing, value)
            return
    if isinstance(last, int):
        while len(cur) <= last:
            cur.append(None)
        cur[last] = value
    else:
        cur[last] = value


def unset_at(obj: dict, parts: list[str | int]) -> bool:
    """Delete ``obj`` at ``parts``. Returns True if anything was removed."""
    if not parts:
        return False
    cur: Any = obj
    for p in parts[:-1]:
        if isinstance(p, int):
            if not isinstance(cur, list) or p >= len(cur):
                return False
            cur = cur[p]
        else:
            if not isinstance(cur, dict) or p not in cur:
                return False
            cur = cur[p]
    last = parts[-1]
    if isinstance(last, int):
        if not isinstance(cur, list) or last >= len(cur):
            return False
        cur.pop(last)
        return True
    if not isinstance(cur, dict) or last not in cur:
        return False
    del cur[last]
    return True


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def parse_value(raw: str, *, strict_json: bool) -> Any:
    """Parse a CLI value. Strict mode requires valid JSON; otherwise try
    JSON first and fall back to a raw string."""
    if strict_json:
        return json.loads(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def _read_or_default() -> dict:
    """Read raw JSON from disk, or build a fresh v2 default if missing."""
    path = config.config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"error: config.json malformed: {e}", file=sys.stderr)
            sys.exit(2)
    # Fall back to packaged defaults so `config set` works on a fresh box.
    defaults = (Path(__file__).parent / "default" / "config.json").resolve()
    if defaults.exists():
        return json.loads(defaults.read_text(encoding="utf-8"))
    return {"version": config.CONFIG_VERSION}


def _write(raw: dict) -> Path:
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(raw, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def cmd_file(_args: argparse.Namespace) -> int:
    print(config.config_path())
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    raw = _read_or_default()
    parts = split_path(args.path)
    value = get_at(raw, parts)
    if value is None:
        return 1
    if args.json:
        print(json.dumps(value, indent=2))
    elif isinstance(value, (dict, list)):
        print(json.dumps(value, indent=2))
    else:
        print(value)
    return 0


def build_ref_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Translate ``--ref-*`` argparse flags into a SecretRef dict.

    Raises SystemExit (via the caller's print+return) if the arg combo
    doesn't match the chosen source.
    """
    src = args.ref_source
    if src == "env":
        if not args.ref_id:
            raise ValueError("--ref-source env requires --ref-id")
        return {"source": "env", "id": args.ref_id}
    if src == "literal":
        if args.ref_value is None:
            raise ValueError("--ref-source literal requires --ref-value")
        return {"source": "literal", "value": args.ref_value}
    if src == "file":
        if not args.ref_path:
            raise ValueError("--ref-source file requires --ref-path")
        out: dict[str, Any] = {"source": "file", "path": args.ref_path}
        if args.ref_key:
            out["key"] = args.ref_key
        return out
    if src == "exec":
        if not args.ref_command:
            raise ValueError("--ref-source exec requires --ref-command")
        out = {"source": "exec", "command": args.ref_command}
        if args.ref_arg:
            out["args"] = list(args.ref_arg)
        return out
    raise ValueError(f"unsupported --ref-source {src!r}")


def cmd_set(args: argparse.Namespace) -> int:
    parts = split_path(args.path)
    if args.ref_source:
        if args.value is not None:
            print("error: pass either <value> OR --ref-source, not both", file=sys.stderr)
            return 2
        try:
            value: Any = build_ref_from_args(args)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    else:
        if args.value is None:
            print("error: missing <value>", file=sys.stderr)
            return 2
        value = parse_value(args.value, strict_json=args.strict_json)

    raw = _read_or_default()
    set_at(raw, parts, value, merge=args.merge, replace=args.replace)
    path = _write(raw)
    print(f"set {args.path} (wrote {path})")
    return 0


def cmd_unset(args: argparse.Namespace) -> int:
    raw = _read_or_default()
    parts = split_path(args.path)
    removed = unset_at(raw, parts)
    if not removed:
        print(f"path not found: {args.path}", file=sys.stderr)
        return 1
    path = _write(raw)
    print(f"unset {args.path} (wrote {path})")
    return 0


_SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|credential)", re.I)


def _walk_secret_slots(obj: Any, path: str = "") -> list[tuple[str, Any]]:
    """Find every leaf whose key name looks like a secret slot.

    A "leaf" is the value at a key matched by ``_SECRET_KEY_RE`` and is
    either a non-dict (string / null) or a SecretRef-shaped dict (one with
    a ``source`` key). Containers — dicts whose key happens to match the
    regex but whose value is a sub-tree (e.g. the openclaw ``secrets`` map)
    — are recursed into instead of being flagged.
    """
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            sub = f"{path}.{k}" if path else k
            is_secret_name = bool(_SECRET_KEY_RE.search(k))
            is_leaf = (not isinstance(v, dict)) or ("source" in v)
            if is_secret_name and is_leaf:
                out.append((sub, v))
                continue
            out.extend(_walk_secret_slots(v, sub))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_walk_secret_slots(v, f"{path}[{i}]"))
    return out


def audit_config(raw: dict) -> dict[str, list[str]]:
    """Categorize every secret slot in ``raw`` as plaintext / unresolved / ok.

    Pure function: doesn't read or write disk, doesn't call ``config.load``.
    Tests pass a hand-built dict and assert on the resulting categories.

    A slot is:
      * **plaintext** — the value is a bare string OR a ``literal`` SecretRef.
        These should be moved to a ``.env`` file with an ``env`` ref.
      * **unresolved** — a structured SecretRef (env/file/exec) that resolves
        to an empty value at audit time. The shape is fine; the data is
        missing.
      * **ok** — resolves to a non-empty value.
      * (skipped) — the slot is null/absent.
    """
    plaintext: list[str] = []
    unresolved: list[str] = []
    ok: list[str] = []
    for path, value in _walk_secret_slots(raw):
        if value is None or value == "":
            continue
        ref = config.parse_ref(value)
        if ref is None:
            # Unparseable shape — flag as plaintext so it can't hide.
            plaintext.append(path)
            continue
        if ref.source == "literal":
            plaintext.append(path)
            continue
        if config.resolve_ref(ref):
            ok.append(path)
        else:
            unresolved.append(path)
    return {"plaintext": plaintext, "unresolved": unresolved, "ok": ok}


def cmd_audit(args: argparse.Namespace) -> int:
    """Scan config.json for plaintext + unresolved SecretRefs.

    Exit codes mirror openclaw's `secrets audit`:
      0 — clean
      1 — plaintext findings
      2 — unresolved refs (higher priority)
    """
    raw = _read_or_default()
    report = audit_config(raw)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if not report["plaintext"] and not report["unresolved"]:
            print(f"clean — {len(report['ok'])} secret slot(s) all resolve via SecretRef")
        else:
            if report["plaintext"]:
                print("PLAINTEXT (move these to a .env file and replace with"
                      " {source: env, id: <NAME>}):")
                for p in report["plaintext"]:
                    print(f"  {p}")
            if report["unresolved"]:
                print("UNRESOLVED (SecretRef shape is fine, but the source"
                      " yields no value):")
                for p in report["unresolved"]:
                    print(f"  {p}")
            if report["ok"]:
                print(f"({len(report['ok'])} other slot(s) resolve cleanly)")
    if report["unresolved"]:
        return 2
    if report["plaintext"]:
        return 1
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Best-effort structural check.

    Loads the config through the same code path the runtime uses; reports
    the resolved version + any obvious errors. Doesn't flag ``literal``
    SecretRefs (use ``coii config audit`` once that lands).
    """
    try:
        cfg = config.load()
    except Exception as e:  # noqa: BLE001
        print(f"invalid: {e}", file=sys.stderr)
        return 1
    report = {
        "path": str(config.config_path()),
        "version": cfg.version,
        "service": {"name": cfg.service.name, "log_level": cfg.service.log_level},
        "linear_enabled": cfg.linear.enabled,
        "models_default": cfg.models.default,
        "providers": sorted(cfg.models.providers.keys()),
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for k, v in report.items():
            print(f"{k}: {v}")
        print("ok")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Wire ``coii config ...`` into a parent argparse subparser group."""
    p = subparsers.add_parser("config", help="read/edit ~/.coii/config.json")
    sub = p.add_subparsers(dest="config_cmd", required=True)

    sub.add_parser("file", help="print the active config path").set_defaults(func=cmd_file)

    g = sub.add_parser("get", help="read a value at a path")
    g.add_argument("path")
    g.add_argument("--json", action="store_true", help="emit raw JSON")
    g.set_defaults(func=cmd_get)

    s = sub.add_parser("set", help="write a value at a path")
    s.add_argument("path")
    s.add_argument("value", nargs="?", default=None)
    s.add_argument("--strict-json", action="store_true",
                   help="require <value> to parse as JSON")
    s.add_argument("--merge", action="store_true",
                   help="deep-merge dicts instead of replacing")
    s.add_argument("--replace", action="store_true",
                   help="(parity with openclaw; plain set already replaces)")
    s.add_argument("--ref-source", choices=("env", "literal", "file", "exec"),
                   help="build a SecretRef instead of taking a value")
    s.add_argument("--ref-id",      help="env source: env var name to read")
    s.add_argument("--ref-value",   help="literal source: the inline value")
    s.add_argument("--ref-path",    help="file source: filesystem path to read")
    s.add_argument("--ref-key",     help="file source (optional): JSON dot-path to dereference")
    s.add_argument("--ref-command", help="exec source: command to run")
    s.add_argument("--ref-arg",     action="append", default=[],
                   help="exec source: command argument (repeatable)")
    s.set_defaults(func=cmd_set)

    u = sub.add_parser("unset", help="delete the entry at a path")
    u.add_argument("path")
    u.set_defaults(func=cmd_unset)

    v = sub.add_parser("validate", help="check the active config loads cleanly")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=cmd_validate)

    a = sub.add_parser("audit", help="flag plaintext + unresolved SecretRefs in config.json")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_audit)
