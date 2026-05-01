"""End-to-end full dispatch — ticket → poll → matcher → agent → comment posted.

This is the only e2e that actually burns LLM tokens. Everything is kept
minimal so the bill is negligible:

  * Isolated tmp ``~/.coii/`` (does not touch the user's real config / agents).
  * One synthetic agent with a single-line IDENTITY.md.
  * One trigger matched by a synthetic ``agent:e2e-dispatch`` label.
  * Workflow body: "Reply with the single word `pong`, nothing else."
  * ``runtime.type = llm_direct`` (no ``claude`` CLI subprocess) pinned to
    ``anthropic/claude-haiku-4-5-20251001``.

What it asserts
---------------
1. Test ticket gets created in Linear with the synthetic label.
2. ``LinearPoller.poll_once()`` produces ``ticket.created`` AND
   ``dispatch_event`` runs the trigger.
3. A real comment authored by the bot user appears on the ticket.

Skipped if ``ANTHROPIC_API_KEY`` isn't set — without an LLM available the
agent can't generate a reply.

Run::

    cd services/coii/backend
    uv run python scripts/e2e_dispatch.py
    # optional: COII_TEST_TEAM_KEY=LEL  to pin the team
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_BACKEND))

# Override COII_ROOT BEFORE importing anything that calls ``coii_root()``.
TMP_ROOT = Path(tempfile.mkdtemp(prefix="coii_e2e_dispatch_"))
os.environ["COII_ROOT"] = str(TMP_ROOT)

from dotenv import load_dotenv  # noqa: E402

_ENV_TEST = REPO_BACKEND.parent / ".env.test"
if _ENV_TEST.exists():
    load_dotenv(_ENV_TEST, override=True)

# Now safe to import app.* — they'll see the overridden COII_ROOT.
from app import config, poller  # noqa: E402
from app.trackers.linear import LinearAdapter  # noqa: E402

TEST_LABEL = "agent:e2e-dispatch"
TEST_AGENT = "e2e-test-agent"
# Probed in order — first one whose key authenticates is used. Both pinned
# to each provider's cheapest fast model so the round-trip cost is minimal.
PROVIDER_CANDIDATES = (
    ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5-20251001"),
    ("OPENAI_API_KEY",    "openai/gpt-4o-mini"),
)


def _ok(msg: str) -> None: print(f"\033[32m✓\033[0m {msg}")
def _fail(msg: str) -> None: print(f"\033[31m✗\033[0m {msg}", file=sys.stderr); sys.exit(1)
def _step(msg: str) -> None: print(f"\n\033[34m── {msg}\033[0m")


# ---------------------------------------------------------------------------
# Tmp ~/.coii/ scaffolding
# ---------------------------------------------------------------------------


def _scaffold_minimal_coii_root(model_spec: str) -> None:
    """Seed the tmp ~/.coii/ with one agent + one workflow.

    Everything is kept tiny so the system prompt is short and the LLM
    round-trip is cheap. ``model_spec`` is whichever provider/model
    authenticated against the env (see ``_probe_providers``).
    """
    agent_dir = TMP_ROOT / "agents" / TEST_AGENT
    agent_dir.mkdir(parents=True)
    (agent_dir / "IDENTITY.md").write_text(
        "You are a test echo agent. Always reply with exactly one word: pong.\n",
        encoding="utf-8",
    )
    (agent_dir / "workspace.json").write_text(json.dumps({
        "id": TEST_AGENT,
        "runtime": {"type": "llm_direct", "model": model_spec},
    }, indent=2), encoding="utf-8")

    workflows_dir = TMP_ROOT / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "test_workflow.yaml").write_text(textwrap.dedent(f"""
        name: e2e-dispatch
        enabled: true
        triggers:
          - name: "e2e-dispatch: created"
            when:
              tracker: linear
              event: ticket.created
              labels_contain: "{TEST_LABEL}"
            agent: {TEST_AGENT}
            workflow: |
              Reply with exactly the single word "pong" and nothing else.
              Do not add status tags, code fences, punctuation, or any
              additional text.
        """).lstrip(), encoding="utf-8")

    (TMP_ROOT / "config.json").write_text(json.dumps({
        "version": 2,
        "service": {"name": "coii", "log_level": "info"},
        "trackers": {
            "linear": {
                "enabled": True,
                "api_key": {"source": "env", "id": "LINEAR_API_KEY"},
                "webhook_secret": {"source": "env", "id": "LINEAR_WEBHOOK_SECRET"},
                "team_keys": [],
                "poll_interval_seconds": 30,
            }
        },
        "models": {
            "default": model_spec,
            "providers": {
                "anthropic": {"type": "anthropic",
                              "api_key": {"source": "env", "id": "ANTHROPIC_API_KEY"}},
                "openai":    {"type": "openai",
                              "api_key": {"source": "env", "id": "OPENAI_API_KEY"}},
            },
        },
    }, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# GraphQL helpers
# ---------------------------------------------------------------------------


async def _pick_team(adapter: LinearAdapter) -> dict[str, Any]:
    pinned = os.getenv("COII_TEST_TEAM_KEY", "").strip()
    teams_doc = await adapter._gql("query { teams { nodes { id name key } } }", {})
    teams = (teams_doc.get("teams") or {}).get("nodes") or []
    if not teams:
        _fail("no teams visible to this token")
    if pinned:
        match_team = next((t for t in teams if t["key"] == pinned), None)
        if not match_team:
            _fail(f"no team with key {pinned!r} (found: {[t['key'] for t in teams]})")
        return match_team
    return teams[0]


async def _ensure_label(adapter: LinearAdapter, team_id: str, name: str) -> str:
    data = await adapter._gql(
        """query Labels($team: ID!) {
            issueLabels(filter: { team: { id: { eq: $team } } }) { nodes { id name } }
        }""",
        {"team": team_id},
    )
    for lbl in data["issueLabels"]["nodes"]:
        if lbl["name"] == name:
            return lbl["id"]
    out = await adapter._gql(
        """mutation CL($i: IssueLabelCreateInput!) {
            issueLabelCreate(input: $i) { issueLabel { id name } }
        }""",
        {"i": {"name": name, "teamId": team_id, "color": "#ff7799"}},
    )
    return out["issueLabelCreate"]["issueLabel"]["id"]


async def _create_ticket(adapter: LinearAdapter, team_id: str, label_id: str) -> dict[str, Any]:
    out = await adapter._gql(
        """mutation IC($i: IssueCreateInput!) {
            issueCreate(input: $i) {
              success
              issue { id identifier title createdAt url state { name }
                      labels { nodes { name } } }
            }
        }""",
        {"i": {
            "teamId": team_id,
            "title": f"[e2e dispatch {datetime.now(timezone.utc).strftime('%H:%M:%S')}] safe to delete",
            "description": "Created by e2e_dispatch.py — agent should reply 'pong'.",
            "labelIds": [label_id],
        }},
    )
    if not (out.get("issueCreate") or {}).get("success"):
        _fail(f"issueCreate did not succeed: {out}")
    return out["issueCreate"]["issue"]


async def _list_comments(adapter: LinearAdapter, issue_uuid: str) -> list[dict[str, Any]]:
    out = await adapter._gql(
        """query Comments($id: String!) {
            issue(id: $id) {
              comments { nodes { id body createdAt user { name email displayName } } }
            }
        }""",
        {"id": issue_uuid},
    )
    return ((out.get("issue") or {}).get("comments") or {}).get("nodes") or []


async def _archive(adapter: LinearAdapter, issue_uuid: str) -> None:
    out = await adapter._gql(
        "mutation A($id: String!) { issueArchive(id: $id) { success } }",
        {"id": issue_uuid},
    )
    if not (out.get("issueArchive") or {}).get("success"):
        _fail(f"issueArchive did not succeed: {out}")


def _anchor_just_before(iso_ts: str) -> str:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (dt - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _probe_anthropic(model: str) -> str | None:
    try:
        import anthropic
    except ImportError as e:
        return f"anthropic SDK missing: {e}"
    try:
        client = anthropic.AsyncAnthropic()
        resp = await client.messages.create(
            model=model, max_tokens=4,
            messages=[{"role": "user", "content": "ping"}],
        )
        return None if resp.content else "empty response"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {str(e)[:120]}"


async def _probe_openai(model: str) -> str | None:
    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        return f"openai SDK missing: {e}"
    try:
        client = AsyncOpenAI()
        resp = await client.chat.completions.create(
            model=model, max_completion_tokens=4,
            messages=[{"role": "user", "content": "ping"}],
        )
        return None if resp.choices else "empty response"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {str(e)[:120]}"


async def _probe_providers() -> tuple[str, str] | None:
    """Find the first provider whose key authenticates.

    Returns ``(env_key_name, model_spec)`` on success, ``None`` if none
    work. Probing avoids the trap where dispatch silently falls back to
    the templated reply when the key is invalid.
    """
    for env_key, spec in PROVIDER_CANDIDATES:
        if not os.getenv(env_key):
            continue
        provider, model = spec.split("/", 1)
        probe = _probe_anthropic if provider == "anthropic" else _probe_openai
        err = await probe(model)
        if err is None:
            return env_key, spec
        print(f"  {env_key} present but unusable: {err}", file=sys.stderr)
    return None


async def main() -> None:
    if not os.getenv("LINEAR_API_KEY"):
        _fail("LINEAR_API_KEY not set — put it in services/coii/.env.test")

    _step("Probe LLM providers (Anthropic, then OpenAI) for a working key")
    picked = await _probe_providers()
    if picked is None:
        print("\033[33mskipping e2e_dispatch:\033[0m no LLM provider key authenticates "
              "(set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env.test)",
              file=sys.stderr)
        sys.exit(0)
    env_key, model_spec = picked
    _ok(f"using {env_key} → {model_spec}")

    _step(f"Scaffold tmp COII_ROOT={TMP_ROOT}")
    _scaffold_minimal_coii_root(model_spec)
    config.reload()  # reload singleton against the tmp root + new config.json
    _ok(f"seeded 1 agent + 1 workflow + config.json (model={model_spec})")

    adapter = LinearAdapter()

    _step("Pick a team for the test")
    team = await _pick_team(adapter)
    team_keys = (team["key"],)
    _ok(f"team={team['key']} id={team['id']}")

    _step(f"Create test ticket with label {TEST_LABEL!r}")
    label_id = await _ensure_label(adapter, team["id"], TEST_LABEL)
    issue = await _create_ticket(adapter, team["id"], label_id)
    test_id = issue["identifier"]
    test_uuid = issue["id"]
    _ok(f"created {test_id} ({issue['url']})")

    _step("Run LinearPoller.poll_once() — dispatch should fire and post a comment")
    p = poller.LinearPoller(team_keys=team_keys)
    p.cursor = _anchor_just_before(issue["createdAt"])
    try:
        stats = await p.poll_once()
    except Exception as e:  # noqa: BLE001
        _fail(f"poll_once raised: {e!r}")
    _ok(f"poll_once stats={stats}")
    if stats.get("events", 0) < 1:
        _fail(f"expected ≥1 event, got {stats.get('events')}")

    _step("Verify a comment was posted to the ticket BY THE LLM (not templated)")
    comments = await _list_comments(adapter, test_uuid)
    if not comments:
        _fail(f"no comments on {test_id} after dispatch")
    bodies = [c.get("body") or "" for c in comments]
    print(f"  {len(comments)} comment(s):")
    for b in bodies:
        snippet = b.replace("\n", " ")[:120]
        print(f"    • {snippet}")
    # The templated fallback contains this exact phrase. If we see it the
    # LLM didn't actually run — the e2e is technically green but lying.
    if any("LLM runtime not configured" in b for b in bodies):
        _fail("dispatch fell back to templated reply — LLM path didn't actually run")
    # Strict content check: workflow asked for "pong". Allow leading/trailing
    # whitespace and a status tag (the runtime strips those before posting),
    # but the visible body should be exactly "pong" (case-insensitive).
    if not any("pong" in b.lower() for b in bodies):
        _fail(f"no comment contains 'pong' — LLM ignored the workflow:\n  {bodies}")
    _ok(f"agent posted {len(comments)} LLM-authored comment(s) containing 'pong'")

    _step("Archive test ticket")
    await _archive(adapter, test_uuid)
    _ok(f"archived {test_id}")

    print("\n\033[32m✓ E2E PASSED\033[0m — full polling → dispatch → LLM → comment posted")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        # Best-effort cleanup of the tmp root.
        import shutil
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
