"""Agent loader test against a temp fake ~/.coii/ dir."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.agents.loader import load_agent


@pytest.fixture
def fake_coii(tmp_path: Path, monkeypatch):
    root = tmp_path / "coii"
    coder = root / "agents" / "coder"
    (coder / "memory").mkdir(parents=True)

    (root / "config.json").write_text(
        '{"default_runtime": {"type":"claude_code"}, '
        '"memory": {"auto_load": {"tier2_days": 2}}}'
    )
    (coder / "workspace.json").write_text("{}")
    (coder / "IDENTITY.md").write_text("# coder identity")
    (coder / "SOUL.md").write_text("# soul body")
    (coder / "AGENTS.md").write_text("# agents body")
    (coder / "TOOLS.md").write_text("# tools body")
    (coder / "LOOP.md").write_text("# loop body")
    (coder / "USER.md").write_text("# user body")
    (coder / "MEMORY.md").write_text("# tier-1 memory")
    (coder / "memory" / "2026-04-28.md").write_text("today log")
    (coder / "memory" / "2026-04-27.md").write_text("yesterday log")

    monkeypatch.setenv("COII_ROOT", str(root))
    return root


def test_load_agent_assembles_prompt(fake_coii: Path):
    ctx = load_agent("coder", today=date(2026, 4, 28))
    assert ctx.name == "coder"
    p = ctx.prompt
    # All identity sections present
    assert "# coder identity" in p
    assert "# soul body" in p
    assert "# agents body" in p
    assert "# tools body" in p
    assert "# loop body" in p
    assert "# user body" in p
    # Tier 1 + tier 2 (today + yesterday)
    assert "# tier-1 memory" in p
    assert "today log" in p
    assert "yesterday log" in p
    # Order: identity files appear before memory
    assert p.index("# coder identity") < p.index("# tier-1 memory")
    assert p.index("# tier-1 memory") < p.index("today log")


def test_missing_agent_raises(fake_coii: Path):
    with pytest.raises(FileNotFoundError):
        load_agent("does-not-exist")


def test_missing_optional_file_is_blank(fake_coii: Path):
    # remove USER.md and reload — should still work
    (fake_coii / "agents" / "coder" / "USER.md").unlink()
    ctx = load_agent("coder", today=date(2026, 4, 28))
    assert "# user body" not in ctx.prompt
    assert "# soul body" in ctx.prompt
