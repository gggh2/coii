"""Issue.update filter tests — drop side-effect updates, keep meaningful ones."""

from __future__ import annotations

import json

from app.trackers.linear import LinearAdapter, _has_meaningful_change


def test_has_meaningful_change_skips_noise():
    assert not _has_meaningful_change({"updatedAt": "x", "commentCount": 1})
    assert not _has_meaningful_change({"subscriberIds": [], "updatedAt": "x"})
    assert not _has_meaningful_change({})


def test_has_meaningful_change_accepts_real_change():
    assert _has_meaningful_change({"stateId": "abc", "updatedAt": "x"})
    assert _has_meaningful_change({"labelIds": ["a", "b"]})
    assert _has_meaningful_change({"title": "new"})
    assert _has_meaningful_change({"assigneeId": None})


def test_issue_update_with_only_comment_count_dropped():
    """The exact shape Linear sends after a comment is posted."""
    a = LinearAdapter(api_key="x", webhook_secret="")
    payload = {
        "type": "Issue",
        "action": "update",
        "updatedFrom": {"updatedAt": "2026-04-28T20:26:14Z", "commentCount": 0},
        "data": {
            "id": "uuid", "identifier": "DEMO-1", "title": "t",
            "state": {"name": "Backlog"},
            "labels": [{"name": "agent:coder"}],
        },
    }
    assert a.parse_webhook(json.dumps(payload).encode(), None) is None


def test_issue_update_with_label_change_kept():
    a = LinearAdapter(api_key="x", webhook_secret="")
    payload = {
        "type": "Issue",
        "action": "update",
        "updatedFrom": {"labelIds": [], "updatedAt": "x"},
        "data": {
            "id": "uuid", "identifier": "DEMO-1", "title": "t",
            "state": {"name": "Backlog"},
            "labels": [{"name": "agent:coder"}],
        },
    }
    ev = a.parse_webhook(json.dumps(payload).encode(), None)
    assert ev is not None and ev.type == "ticket.updated"


def test_issue_update_assigneeid_still_routes_to_assigned():
    """Assignee changes route to ticket.assigned regardless of noise filter."""
    a = LinearAdapter(api_key="x", webhook_secret="")
    payload = {
        "type": "Issue",
        "action": "update",
        "updatedFrom": {"assigneeId": None, "updatedAt": "x"},
        "data": {
            "id": "uuid", "identifier": "DEMO-1", "title": "t",
            "assignee": {"name": "@coder"},
        },
    }
    ev = a.parse_webhook(json.dumps(payload).encode(), None)
    assert ev is not None and ev.type == "ticket.assigned"
