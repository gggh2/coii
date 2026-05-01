"""coii — CLI entrypoint.

Usage:
    coii init                Seed ~/.coii/ from packaged defaults.
                                     Skips files that already exist; safe to
                                     re-run after package upgrades.
    coii serve [--port N]    Run the FastAPI backend.
    coii config ...          Read/edit ~/.coii/config.json (file/get/set/unset/validate).
    coii uninstall           Delete ~/.coii/ (asks for confirmation).
    coii version             Print the installed version.

The runtime root is `~/.coii/` (override with $COII_ROOT). Identity files,
workflows, and `config.json` are seeded from the packaged defaults; tickets,
agent memory, and per-agent `MEMORY.md` accumulate there over time.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from app.util import coii_root, defaults_root


def _seed(src: Path, dst: Path) -> tuple[int, int]:
    """Recursively copy `src` -> `dst`, skipping any file that already exists.

    Returns (copied, skipped) counts. Idempotent — safe to call repeatedly.
    """
    copied = 0
    skipped = 0
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        target = dst / rel
        if target.exists():
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied, skipped


def cmd_init(_args: argparse.Namespace) -> int:
    src = defaults_root()
    dst = coii_root()
    if not src.is_dir():
        print(f"error: packaged defaults not found at {src}", file=sys.stderr)
        return 2
    dst.mkdir(parents=True, exist_ok=True)
    copied, skipped = _seed(src, dst)
    print(f"seeded {dst}: {copied} new, {skipped} preserved")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    if args.wizard:
        from app.setup_wizard import main as wizard_main
        wizard_argv = ["--non-interactive"] if args.non_interactive else []
        return wizard_main(wizard_argv)
    # Plain `coii setup` = `coii init` (idempotent seed).
    return cmd_init(args)


def cmd_version(_args: argparse.Namespace) -> int:
    try:
        from importlib.metadata import version
        print(version("coii"))
    except Exception:
        print("unknown (not installed via pip/uv)")
    return 0


def _summarize(target: Path) -> str:
    """One-line breakdown of what's about to be deleted."""
    parts: list[str] = []
    tickets = target / "tickets"
    if tickets.is_dir():
        n = sum(1 for _ in tickets.iterdir() if _.is_dir())
        if n:
            parts.append(f"{n} ticket{'s' if n != 1 else ''}")
    agents = target / "agents"
    if agents.is_dir():
        n = sum(1 for _ in agents.iterdir() if _.is_dir())
        if n:
            parts.append(f"{n} agent{'s' if n != 1 else ''}")
    workflows = target / "workflows"
    if workflows.is_dir():
        n = sum(1 for _ in workflows.glob("*_workflow.yaml"))
        if n:
            parts.append(f"{n} workflow{'s' if n != 1 else ''}")
    if (target / ".git").is_dir():
        parts.append("a git repo")
    return ", ".join(parts) if parts else "(empty)"


def cmd_uninstall(args: argparse.Namespace) -> int:
    target = coii_root()
    if not target.exists():
        print(f"{target} does not exist; nothing to remove")
        return 0

    print(f"About to delete: {target}")
    print(f"  Includes: {_summarize(target)}")

    if args.dry_run:
        print("(dry-run — no changes made)")
        return 0

    if not args.yes:
        try:
            ans = input("Type 'yes' to confirm: ").strip().lower()
        except EOFError:
            ans = ""
        if ans != "yes":
            print("aborted")
            return 1

    shutil.rmtree(target)
    print(f"✓ removed {target}")
    print("To remove the CLI binary too: uv tool uninstall coii")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="coii")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="seed ~/.coii/ from packaged defaults").set_defaults(func=cmd_init)

    setup = sub.add_parser("setup", help="initialize ~/.coii (use --wizard for the interactive flow)")
    setup.add_argument("--wizard", action="store_true", help="run the setup wizard")
    setup.add_argument("--non-interactive", action="store_true",
                       help="read wizard answers from env vars (COII_WIZARD_*, LINEAR_*)")
    setup.set_defaults(func=cmd_setup)

    serve = sub.add_parser("serve", help="run the FastAPI backend")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=3001)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    from app import config_cli
    config_cli.register(sub)

    un = sub.add_parser("uninstall", help="delete ~/.coii/ (asks first)")
    un.add_argument("--yes", action="store_true", help="skip confirmation prompt")
    un.add_argument("--dry-run", action="store_true", help="show what would be removed")
    un.set_defaults(func=cmd_uninstall)

    sub.add_parser("version", help="print installed version").set_defaults(func=cmd_version)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
