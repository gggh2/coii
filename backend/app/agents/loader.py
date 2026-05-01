"""Agent workspace loader.

Reads ~/.coii/agents/<name>/ — workspace.json + identity markdown
(IDENTITY/SOUL/AGENTS/TOOLS/LOOP/USER.md) + MEMORY.md (Tier 1) +
memory/<today>.md, memory/<yesterday>.md (Tier 2 auto-load).

Identity files are seeded on `coii init` from the packaged defaults
in app/default/agents/<name>/. After that, everything (defaults + memory)
lives together under ~/.coii/agents/<name>/, edited by the operator and
mutated by the agent itself.

Concatenates into a single prompt string in the order the PRD §7.4 specifies.
Tier 3 is NOT loaded here — agent retrieves it on demand via memory_search /
memory_get tools (Phase 2). We only assemble what gets pushed into context.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from app.util import coii_root

log = logging.getLogger(__name__)

# Order matters — see PRD §7.4.
IDENTITY_FILES: tuple[str, ...] = (
    "IDENTITY.md",
    "SOUL.md",
    "AGENTS.md",
    "TOOLS.md",
    "LOOP.md",
    "USER.md",
)


@dataclass(frozen=True)
class WorkspaceConfig:
    """Effective config after merging global config.json with workspace.json."""
    runtime: dict = field(default_factory=dict)
    memory: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AgentContext:
    """Everything an Agent needs to act, packaged.

    `prompt` is the assembled system prompt (markdown) ready to feed to a
    runtime. Phase 1 just logs it; Phase 2 will pass it to Claude Code.
    """
    name: str
    workspace_path: Path
    config: WorkspaceConfig
    prompt: str
    sections: dict[str, str]  # section name -> raw content (for debugging)


def load_global_config() -> dict:
    path = coii_root() / "config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error("config.json malformed: %s", e)
        return {}


def load_agent(name: str, *, today: date | None = None) -> AgentContext:
    """Read an Agent's workspace and assemble its prompt.

    `today` is injected for testability; defaults to date.today().
    """
    today = today or date.today()

    ws_dir = coii_root() / "agents" / name
    if not ws_dir.is_dir():
        raise FileNotFoundError(f"agent workspace not found: {ws_dir}")

    config = _resolve_config(ws_dir)
    sections: dict[str, str] = {}

    for filename in IDENTITY_FILES:
        sections[filename] = _read_or_blank(ws_dir / filename)

    sections["MEMORY.md"] = _read_or_blank(ws_dir / "MEMORY.md")

    tier2_days = int(((config.memory or {}).get("auto_load") or {}).get("tier2_days", 2))
    for offset in range(tier2_days):
        d = today - timedelta(days=offset)
        key = f"memory/{d.isoformat()}.md"
        sections[key] = _read_or_blank(ws_dir / "memory" / f"{d.isoformat()}.md")

    prompt = _assemble_prompt(name, sections)

    return AgentContext(
        name=name,
        workspace_path=ws_dir,
        config=config,
        prompt=prompt,
        sections=sections,
    )


def _read_or_blank(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("could not read %s: %s", path, e)
        return ""


def _resolve_config(ws_dir: Path) -> WorkspaceConfig:
    """Deep-merge global config.json with workspace.json (workspace wins)."""
    global_cfg = load_global_config()
    ws_cfg_path = ws_dir / "workspace.json"
    ws_cfg: dict = {}
    if ws_cfg_path.exists():
        try:
            ws_cfg = json.loads(ws_cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            log.error("%s malformed: %s", ws_cfg_path, e)

    merged = _deep_merge(global_cfg.get("default_runtime", {}), ws_cfg.get("runtime", {}))
    memory = _deep_merge(global_cfg.get("memory", {}), ws_cfg.get("memory", {}))

    return WorkspaceConfig(
        runtime=merged,
        memory=memory,
        raw={"global": global_cfg, "workspace": ws_cfg},
    )


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base or {})
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _assemble_prompt(name: str, sections: dict[str, str]) -> str:
    parts: list[str] = [f"# Agent: {name}\n"]
    for filename in IDENTITY_FILES:
        body = sections.get(filename, "").strip()
        if body:
            parts.append(f"\n<!-- {filename} -->\n{body}\n")
    mem = sections.get("MEMORY.md", "").strip()
    if mem:
        parts.append(f"\n<!-- MEMORY.md (Tier 1) -->\n{mem}\n")
    for key, body in sections.items():
        if not key.startswith("memory/"):
            continue
        body = body.strip()
        if body:
            parts.append(f"\n<!-- {key} (Tier 2) -->\n{body}\n")
    return "".join(parts)
