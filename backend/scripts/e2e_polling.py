"""End-to-end verification of the Linear polling pipeline.

Covers what unit tests can't: the full polling chain hitting the real Linear
API, plus dispatch_event integration so we know the matcher / trigger /
agent-load layers run without crashing on real payloads.

Pipeline scenarios covered (excluding webhook — see scripts/e2e_demo.py):

  Phase A — ticket.created
    Create a ticket with NO ``agent:coder`` label, anchor the cursor just
    before its createdAt, and verify it surfaces. Then run
    ``LinearPoller.poll_once()`` so dispatch_event also runs (matched=0,
    no agent fires, no LLM tokens burned).

  Phase B — ticket.updated
    Apply a benign ``test:e2e-poller`` label (not matched by any workflow).
    Verify the event surfaces with the new label and the cursor advances.

  Phase C — ticket.commented
    Post a non-mention comment. Verify it surfaces with the right type and
    actor, exercising the sparse-event enrichment path.

  Phase D — empty-poll idempotency
    With nothing new on this ticket, ``poll_changes`` does NOT replay it.

  Phase E — multi-team_keys filter
    Polling with ``(real_team, "ZZZZZ")`` still surfaces the test ticket;
    bogus team keys are silently filtered out, real ones still match.

  Phase F — cleanup
    Archive the test ticket; reset ``~/.coii/state/linear_poller.json`` so
    live polling doesn't replay this test window.

Auto-loads credentials from ``services/coii/.env.test`` (gitignored). Copy
``.env.local_deploy`` to ``.env.test`` to reuse the same secrets, or paste
a fresh personal API token into ``.env.test``.

Run::

    cd services/coii/backend
    uv run python scripts/e2e_polling.py
    # optional: COII_TEST_TEAM_KEY=LEL  to pin the team
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_BACKEND))

from dotenv import load_dotenv  # noqa: E402

# Load .env.test (gitignored) before anything else imports os.getenv-using code.
_ENV_TEST = REPO_BACKEND.parent / ".env.test"
if _ENV_TEST.exists():
    load_dotenv(_ENV_TEST, override=True)
else:
    print(
        f"\033[33m![\033[0m  {_ENV_TEST} not found — falling back to ambient env\n"
        f"   create it with: cp services/coii/.env.local_deploy services/coii/.env.test",
        file=sys.stderr,
    )

from app import poller  # noqa: E402
from app.trackers.linear import LinearAdapter  # noqa: E402
from app.trackers.types import TicketEvent  # noqa: E402
from app.util import coii_root  # noqa: E402

TEST_LABEL = "test:e2e-poller"  # deliberately not agent:coder so no trigger fires
PROPAGATION_SLEEP = 3.0          # seconds Linear needs to settle a write


def _ok(msg: str) -> None: print(f"\033[32m✓\033[0m {msg}")
def _fail(msg: str) -> None: print(f"\033[31m✗\033[0m {msg}", file=sys.stderr); sys.exit(1)
def _step(msg: str) -> None: print(f"\n\033[34m── {msg}\033[0m")


# ---------------------------------------------------------------------------
# GraphQL helpers
# ---------------------------------------------------------------------------


async def _pick_team(adapter: LinearAdapter) -> dict[str, Any]:
    pinned = os.getenv("COII_TEST_TEAM_KEY", "").strip()
    teams_doc = await adapter._gql(
        "query { teams { nodes { id name key } } }", {},
    )
    teams = (teams_doc.get("teams") or {}).get("nodes") or []
    if not teams:
        _fail("no teams visible to this token")
    if pinned:
        match_team = next((t for t in teams if t["key"] == pinned), None)
        if not match_team:
            _fail(f"no team with key {pinned!r} (found: {[t['key'] for t in teams]})")
        return match_team
    return teams[0]


async def _create_ticket(adapter: LinearAdapter, team_id: str) -> dict[str, Any]:
    title = f"[e2e poller {datetime.now(timezone.utc).strftime('%H:%M:%S')}] safe to delete"
    out = await adapter._gql(
        """
        mutation IssueCreate($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            success
            issue { id identifier title createdAt updatedAt url
                    state { name } labels { nodes { name } } }
          }
        }
        """,
        {"input": {
            "teamId": team_id,
            "title": title,
            "description": "Created by services/coii/backend/scripts/e2e_polling.py. "
                           "Auto-archived after the test. No agent:coder label so no triggers fire.",
        }},
    )
    if not (out.get("issueCreate") or {}).get("success"):
        _fail(f"issueCreate did not succeed: {out}")
    return out["issueCreate"]["issue"]


async def _ensure_label(adapter: LinearAdapter, team_id: str, name: str) -> str:
    data = await adapter._gql(
        """
        query Labels($team: ID!) {
          issueLabels(filter: { team: { id: { eq: $team } } }) {
            nodes { id name }
          }
        }
        """,
        {"team": team_id},
    )
    for lbl in data["issueLabels"]["nodes"]:
        if lbl["name"] == name:
            return lbl["id"]
    out = await adapter._gql(
        """
        mutation CreateLabel($input: IssueLabelCreateInput!) {
          issueLabelCreate(input: $input) { issueLabel { id name } }
        }
        """,
        {"input": {"name": name, "teamId": team_id, "color": "#999999"}},
    )
    return out["issueLabelCreate"]["issueLabel"]["id"]


async def _add_label(adapter: LinearAdapter, issue_uuid: str, label_id: str) -> None:
    await adapter._gql(
        """
        mutation IssueAddLabel($id: String!, $labelId: String!) {
          issueAddLabel(id: $id, labelId: $labelId) { success }
        }
        """,
        {"id": issue_uuid, "labelId": label_id},
    )


async def _post_comment(adapter: LinearAdapter, issue_uuid: str, body: str) -> str:
    out = await adapter._gql(
        """
        mutation CommentCreate($input: CommentCreateInput!) {
          commentCreate(input: $input) { success comment { id } }
        }
        """,
        {"input": {"issueId": issue_uuid, "body": body}},
    )
    if not (out.get("commentCreate") or {}).get("success"):
        _fail(f"commentCreate did not succeed: {out}")
    return out["commentCreate"]["comment"]["id"]


async def _archive(adapter: LinearAdapter, issue_uuid: str) -> None:
    out = await adapter._gql(
        "mutation Archive($id: String!) { issueArchive(id: $id) { success } }",
        {"id": issue_uuid},
    )
    if not (out.get("issueArchive") or {}).get("success"):
        _fail(f"issueArchive did not succeed: {out}")


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------


def _anchor_just_before(iso_ts: str) -> str:
    """Return ``iso_ts`` shifted back one second.

    Linear treats the cursor as strictly less-than, so a cursor identical
    to ``createdAt`` would skip the very ticket we want to surface.
    """
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (dt - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _matching_event(events: list[TicketEvent], ticket_id: str, type_: str) -> TicketEvent:
    """First event matching (ticket_id, type). Fails with a diagnostic dump."""
    found = [e for e in events if e.ticket.id == ticket_id and e.type == type_]
    if not found:
        for e in events:
            print(f"    saw {e.type} ticket={e.ticket.id} updated={e.raw.get('updatedAt')}")
        _fail(f"expected {type_} for {ticket_id}; got {len(events)} other event(s)")
    return found[0]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    if not os.getenv("LINEAR_API_KEY"):
        _fail("LINEAR_API_KEY not set — put it in services/coii/.env.test")

    adapter = LinearAdapter()

    # ── Auth check
    _step("Auth check (viewer query)")
    try:
        v = await adapter._gql("query { viewer { id name email } }", {})
    except Exception as e:
        _fail(f"viewer query failed: {e}\n  Token probably expired")
    me = (v.get("viewer") or {}).get("name") or (v.get("viewer") or {}).get("email") or "?"
    _ok(f"authenticated as {me}")

    # ── Team discovery
    _step("Discover teams")
    team = await _pick_team(adapter)
    team_keys = (team["key"],)
    _ok(f"using team key={team['key']} id={team['id']}")

    # ── Create test ticket
    _step("Create test ticket (no agent:coder label — dispatch must match 0 triggers)")
    issue = await _create_ticket(adapter, team["id"])
    test_id = issue["identifier"]
    test_uuid = issue["id"]
    test_url = issue["url"]
    _ok(f"created {test_id} ({test_url})")

    p = poller.LinearPoller(team_keys=team_keys)
    cursor = _anchor_just_before(issue["createdAt"])
    p.cursor = cursor

    # ── Phase A — ticket.created (and exercise dispatch_event via poll_once)
    _step(f"Phase A: ticket.created (cursor anchored before {issue['createdAt']})")
    events, new_cursor = await adapter.poll_changes(since_iso=p.cursor, team_keys=team_keys)
    _matching_event(events, test_id, "ticket.created")
    _ok(f"surfaced ticket.created for {test_id}")

    # Now run a full poll_once — this calls dispatch_event for each event,
    # which in turn runs the matcher and (since no triggers match a label-less
    # ticket) returns matched=0. We're verifying the integration path runs
    # without crashing.
    p.cursor = cursor  # reset so poll_once sees the same window
    stats = await p.poll_once()
    if stats.get("events", 0) < 1:
        _fail(f"poll_once reported {stats.get('events')} events (expected ≥1)")
    _ok(f"poll_once + dispatch_event ran cleanly: {stats}")

    # ── Phase B — ticket.updated
    _step(f"Phase B: ticket.updated (apply '{TEST_LABEL}' label)")
    label_id = await _ensure_label(adapter, team["id"], TEST_LABEL)
    await _add_label(adapter, test_uuid, label_id)
    await asyncio.sleep(PROPAGATION_SLEEP)

    cursor_before_b = p.cursor
    events, new_cursor = await adapter.poll_changes(since_iso=p.cursor, team_keys=team_keys)
    evt = _matching_event(events, test_id, "ticket.updated")
    if TEST_LABEL not in evt.ticket.labels:
        _fail(f"ticket.updated event missing {TEST_LABEL!r}; saw {list(evt.ticket.labels)}")
    _ok(f"surfaced ticket.updated with labels={list(evt.ticket.labels)}")
    p.cursor = new_cursor
    if p.cursor == cursor_before_b:
        _fail("cursor did not advance after ticket.updated")
    _ok("cursor advanced past update")

    # ── Phase C — ticket.commented (also exercises sparse-event enrichment)
    _step("Phase C: ticket.commented (post a non-mention comment)")
    await _post_comment(adapter, test_uuid, "test comment from e2e_polling.py — ignore me")
    await asyncio.sleep(PROPAGATION_SLEEP)

    events, new_cursor = await adapter.poll_changes(since_iso=p.cursor, team_keys=team_keys)
    evt = _matching_event(events, test_id, "ticket.commented")
    _ok(f"surfaced ticket.commented on {test_id} (actor={evt.actor!r})")
    p.cursor = new_cursor

    # ── Phase D — empty-poll idempotency
    _step("Phase D: empty poll — our ticket isn't replayed")
    cursor_before_d = p.cursor
    events, new_cursor = await adapter.poll_changes(since_iso=p.cursor, team_keys=team_keys)
    test_events = [e for e in events if e.ticket.id == test_id]
    if test_events:
        _fail(f"empty-poll replayed {len(test_events)} stale event(s) for {test_id}")
    if new_cursor != cursor_before_d:
        # Other tickets in this team may have been updated during the test
        # window. Cursor advancing because of THEM is fine; we only assert
        # OUR ticket didn't surface again.
        print(f"  (cursor advanced from {cursor_before_d} → {new_cursor} "
              f"due to other workspace activity — fine)")
    _ok(f"empty poll: {len(events)} new event(s), {test_id} not replayed")

    # ── Phase E — multi team_keys filter
    _step("Phase E: multi team_keys — adding a fake second team key still polls real one")
    multi_team_keys = team_keys + ("ZZZZZ",)  # real + non-existent
    multi_events, _ = await adapter.poll_changes(
        since_iso=_anchor_just_before(issue["createdAt"]),
        team_keys=multi_team_keys,
    )
    multi_test_evts = [e for e in multi_events if e.ticket.id == test_id]
    if not multi_test_evts:
        _fail(f"multi-team poll {multi_team_keys} didn't surface {test_id}")
    _ok(f"poll_changes with team_keys={multi_team_keys} surfaced {len(multi_test_evts)} event(s) for {test_id}")

    # ── Phase F — cleanup
    _step("Phase F: archive + reset poller cursor")
    await _archive(adapter, test_uuid)
    _ok(f"archived {test_id}")

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    poller._save_cursor(now_iso)
    state_path = coii_root() / "state" / "linear_poller.json"
    written = json.loads(state_path.read_text())
    if written.get("cursor") != now_iso:
        _fail(f"cursor reset failed: {written}")
    _ok(f"cursor at {state_path} = {now_iso}")

    print("\n\033[32m✓ E2E PASSED\033[0m — polling (created / updated / commented) + dispatch integration")


if __name__ == "__main__":
    asyncio.run(main())
