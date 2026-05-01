"""End-to-end webhook demo driver.

Exercises the webhook path against a real Linear workspace:

  1. Read API key + webhook secret + team key from .env.local_deploy
  2. Resolve the team UUID via GraphQL (no hardcoded workspace identifiers)
  3. Apply / remove labels to put a fresh test ticket through trigger states
  4. For each state, build a webhook payload that mirrors what Linear
     would have sent, sign it with LINEAR_WEBHOOK_SECRET, POST to the
     local /webhooks/linear endpoint, and watch the comment appear on
     the real ticket via the adapter.

For the polling path (no gateway required) see scripts/e2e_linear_poll.py.

Run with:
    uv run python scripts/e2e_demo.py

Required env (set by `./onboard`):
    LINEAR_API_KEY
    LINEAR_WEBHOOK_SECRET
    LINEAR_TEAM_KEY        # e.g. "ENG", "DEMO" — looked up at runtime
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load env from the project-level .env.local_deploy (same path main.py uses).
ROOT = Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env.local_deploy")

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.trackers.linear import LinearAdapter  # noqa: E402

BACKEND = os.getenv("COII_BACKEND_URL", "http://127.0.0.1:3003")
LABEL_NAME = "agent:coder"


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _team_id(adapter: LinearAdapter, team_key: str) -> tuple[str, str]:
    """Look up team UUID + display name by Linear team key (e.g. ``ENG``)."""
    query = """
    query Teams { teams { nodes { id key name } } }
    """
    data = await adapter._gql(query, {})
    for t in data["teams"]["nodes"]:
        if t["key"].upper() == team_key.upper():
            return t["id"], t["name"]
    raise SystemExit(
        f"no Linear team with key {team_key!r} visible to this OAuth token. "
        f"Available: {[t['key'] for t in data['teams']['nodes']]}"
    )


async def _ensure_label(adapter: LinearAdapter, team_id: str) -> str:
    """Find or create the agent:coder label on the configured team."""
    query = """
    query Labels($team: ID!) {
      issueLabels(filter: { team: { id: { eq: $team } } }) {
        nodes { id name }
      }
    }
    """
    data = await adapter._gql(query, {"team": team_id})
    for lbl in data["issueLabels"]["nodes"]:
        if lbl["name"] == LABEL_NAME:
            return lbl["id"]

    mutation = """
    mutation CreateLabel($input: IssueLabelCreateInput!) {
      issueLabelCreate(input: $input) { issueLabel { id name } }
    }
    """
    out = await adapter._gql(mutation, {
        "input": {"name": LABEL_NAME, "teamId": team_id, "color": "#5e6ad2"},
    })
    return out["issueLabelCreate"]["issueLabel"]["id"]


async def _state_id(adapter: LinearAdapter, team_id: str, name: str) -> str:
    query = """
    query States($teamId: ID!) {
      workflowStates(filter: { team: { id: { eq: $teamId } } }) {
        nodes { id name }
      }
    }
    """
    data = await adapter._gql(query, {"teamId": team_id})
    for s in data["workflowStates"]["nodes"]:
        if s["name"].lower() == name.lower():
            return s["id"]
    raise ValueError(f"no state named {name!r}")


async def _create_ticket(adapter: LinearAdapter, team_id: str, label_id: str) -> dict:
    mutation = """
    mutation Create($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        issue { id identifier title state { name } labels { nodes { name } } url team { id name } }
      }
    }
    """
    out = await adapter._gql(mutation, {
        "input": {
            "teamId": team_id,
            "title": "[demo] Phase 1 e2e — please ignore",
            "description": "Created by e2e_demo.py — proves backend can post comments.",
            "labelIds": [label_id],
        },
    })
    return out["issueCreate"]["issue"]


async def _move_state(
    adapter: LinearAdapter, team_id: str, issue_uuid: str, state_name: str,
) -> None:
    state_id = await _state_id(adapter, team_id, state_name)
    mutation = """
    mutation Update($id: String!, $input: IssueUpdateInput!) {
      issueUpdate(id: $id, input: $input) { success }
    }
    """
    await adapter._gql(mutation, {"id": issue_uuid, "input": {"stateId": state_id}})


def _webhook_body(
    issue: dict, state_name: str, labels: list[str], team_name: str,
) -> bytes:
    """Build a payload shaped like what Linear sends for issue.update."""
    body = {
        "type": "Issue",
        "action": "update",
        "data": {
            "id": issue["id"],
            "identifier": issue["identifier"],
            "title": issue["title"],
            "description": "",
            "url": issue["url"],
            "labels": [{"name": n} for n in labels],
            "state": {"name": state_name},
            "team": {"name": team_name},
        },
    }
    return json.dumps(body).encode("utf-8")


async def _post_webhook(body: bytes, secret: str) -> int:
    sig = _sign(secret, body)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"{BACKEND}/webhooks/linear",
            content=body,
            headers={
                "Content-Type": "application/json",
                "Linear-Signature": sig,
                "Linear-Delivery": "demo",
            },
        )
    return r.status_code


async def main() -> int:
    token = os.getenv("LINEAR_API_KEY")
    secret = os.getenv("LINEAR_WEBHOOK_SECRET")
    team_key = os.getenv("LINEAR_TEAM_KEY")
    missing = [
        n for n, v in [
            ("LINEAR_API_KEY", token),
            ("LINEAR_WEBHOOK_SECRET", secret),
            ("LINEAR_TEAM_KEY", team_key),
        ] if not v
    ]
    if missing:
        print(f"missing env vars: {', '.join(missing)} — run ./onboard first",
              file=sys.stderr)
        return 1

    adapter = LinearAdapter(api_key=token, webhook_secret=secret)

    print(f"→ resolving Linear team {team_key!r}")
    team_id, team_name = await _team_id(adapter, team_key)
    print(f"  team: {team_name} ({team_id})")

    print("→ ensuring 'agent:coder' label exists")
    label_id = await _ensure_label(adapter, team_id)
    print(f"  label id: {label_id}")

    print("→ creating test ticket")
    issue = await _create_ticket(adapter, team_id, label_id)
    print(f"  {issue['identifier']} ({issue['url']})")

    # Scenario A: trigger #1 — labels_contain: agent:coder
    print("\n→ scenario A: ticket.updated with label agent:coder (plan-first)")
    body = _webhook_body(issue, "Todo", [LABEL_NAME], team_name)
    print(f"  webhook POST → {await _post_webhook(body, secret)}")
    await asyncio.sleep(2.0)

    # Scenario B: trigger #2 — ticket_status: In Progress
    print("\n→ scenario B: move to 'In Progress' (full-auto)")
    await _move_state(adapter, team_id, issue["id"], "In Progress")
    body = _webhook_body(issue, "In Progress", [LABEL_NAME], team_name)
    print(f"  webhook POST → {await _post_webhook(body, secret)}")
    await asyncio.sleep(2.0)

    # Scenario C: trigger #3 — combined Done + label
    print("\n→ scenario C: move to 'Done' (review-only via combo trigger)")
    await _move_state(adapter, team_id, issue["id"], "Done")
    body = _webhook_body(issue, "Done", [LABEL_NAME], team_name)
    print(f"  webhook POST → {await _post_webhook(body, secret)}")
    await asyncio.sleep(2.0)

    print(f"\n✓ done. Open {issue['url']} to see four comments (one per matched trigger).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
