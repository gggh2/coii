"""Linear adapter parsing tests — covers webhook signature + payload shapes."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.trackers.linear import LinearAdapter


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_verification_passes():
    a = LinearAdapter(api_key="x", webhook_secret="s")
    body = json.dumps({"type": "Issue", "action": "create", "data": {"id": "abc", "title": "t"}}).encode()
    sig = _sign("s", body)
    assert a.parse_webhook(body, sig) is not None


def test_signature_mismatch_raises():
    a = LinearAdapter(api_key="x", webhook_secret="s")
    body = b'{"type":"Issue","action":"create","data":{}}'
    with pytest.raises(PermissionError):
        a.parse_webhook(body, "bad")


def test_no_secret_skips_verification():
    a = LinearAdapter(api_key="x", webhook_secret="")
    body = json.dumps({"type": "Issue", "action": "create", "data": {"id": "x", "title": "t"}}).encode()
    ev = a.parse_webhook(body, signature=None)
    assert ev is not None
    assert ev.type == "ticket.created"


def test_issue_update_with_assignee_change_becomes_assigned():
    a = LinearAdapter(api_key="x", webhook_secret="")
    payload = {
        "type": "Issue",
        "action": "update",
        "updatedFrom": {"assigneeId": None},
        "data": {
            "id": "uuid", "identifier": "ENG-1", "title": "t",
            "assignee": {"name": "@coder"},
        },
    }
    ev = a.parse_webhook(json.dumps(payload).encode(), None)
    assert ev is not None and ev.type == "ticket.assigned"
    assert ev.ticket.assignee == "@coder"


def test_comment_event_extracts_issue():
    a = LinearAdapter(api_key="x", webhook_secret="")
    payload = {
        "type": "Comment",
        "action": "create",
        "data": {
            "id": "c1",
            "body": "go",
            "issue": {"id": "uuid", "identifier": "ENG-1", "title": "t",
                      "labels": [{"name": "agent:coder"}],
                      "state": {"name": "In Progress"}},
            "user": {"name": "alice"},
        },
    }
    ev = a.parse_webhook(json.dumps(payload).encode(), None)
    assert ev is not None and ev.type == "ticket.commented"
    assert ev.ticket.id == "ENG-1"
    assert "agent:coder" in ev.ticket.labels
    assert ev.ticket.status == "In Progress"


def test_unknown_type_returns_none():
    a = LinearAdapter(api_key="x", webhook_secret="")
    payload = {"type": "Reaction", "action": "create", "data": {}}
    assert a.parse_webhook(json.dumps(payload).encode(), None) is None


def test_labels_connection_shape_normalized():
    a = LinearAdapter(api_key="x", webhook_secret="")
    payload = {
        "type": "Issue",
        "action": "create",
        "data": {
            "id": "uuid", "identifier": "ENG-1", "title": "t",
            "labels": {"nodes": [{"name": "agent:coder"}, {"name": "bug"}]},
        },
    }
    ev = a.parse_webhook(json.dumps(payload).encode(), None)
    assert ev is not None
    assert set(ev.ticket.labels) == {"agent:coder", "bug"}
