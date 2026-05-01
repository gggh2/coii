"""Polling tests — exercise the GraphQL response → TicketEvent normalization
and cursor persistence without hitting the network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app import poller
from app.trackers.linear import LinearAdapter


# ---------------------------------------------------------------------------
# Helpers — build a fake Linear GraphQL `issues` response.
# ---------------------------------------------------------------------------

def _issue_node(
    *,
    identifier: str,
    created_at: str,
    updated_at: str,
    labels: tuple[str, ...] = (),
    state: str = "Todo",
    comments: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    return {
        "id": identifier,
        "identifier": identifier,
        "title": f"title-{identifier}",
        "description": "",
        "url": f"https://linear.app/issue/{identifier}",
        "createdAt": created_at,
        "updatedAt": updated_at,
        "state": {"name": state},
        "assignee": None,
        "labels": {"nodes": [{"name": n} for n in labels]},
        "project": None,
        "team": {"name": "Eng", "key": "ENG"},
        "comments": {"nodes": list(comments)},
    }


def _comment(*, id_: str, body: str, created_at: str, user: dict | None = None) -> dict[str, Any]:
    return {
        "id": id_,
        "body": body,
        "createdAt": created_at,
        "user": user or {"id": "u1", "name": "Alice", "email": "alice@example.com"},
    }


# ---------------------------------------------------------------------------
# poll_changes — normalization
# ---------------------------------------------------------------------------

class _FakeAdapter(LinearAdapter):
    """LinearAdapter with _gql stubbed so we can inject GraphQL responses."""

    def __init__(self, response_data: dict[str, Any]) -> None:
        super().__init__(api_key="fake")
        self._response = response_data

    async def _gql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return self._response


@pytest.mark.asyncio
async def test_new_issue_emits_ticket_created():
    adapter = _FakeAdapter({
        "issues": {
            "nodes": [
                _issue_node(
                    identifier="ENG-1",
                    created_at="2026-04-30T10:00:05Z",
                    updated_at="2026-04-30T10:00:05Z",
                ),
            ],
            "pageInfo": {"hasNextPage": False},
        }
    })
    events, new_cursor = await adapter.poll_changes(
        since_iso="2026-04-30T10:00:00Z", team_keys=("ENG",),
    )
    assert [e.type for e in events] == ["ticket.created"]
    assert events[0].ticket.id == "ENG-1"
    assert new_cursor == "2026-04-30T10:00:05Z"


@pytest.mark.asyncio
async def test_existing_issue_updated_emits_ticket_updated():
    adapter = _FakeAdapter({
        "issues": {
            "nodes": [
                _issue_node(
                    identifier="ENG-2",
                    created_at="2026-04-29T08:00:00Z",   # before cursor
                    updated_at="2026-04-30T10:00:05Z",   # after cursor
                ),
            ],
            "pageInfo": {"hasNextPage": False},
        }
    })
    events, _ = await adapter.poll_changes(
        since_iso="2026-04-30T10:00:00Z", team_keys=("ENG",),
    )
    assert [e.type for e in events] == ["ticket.updated"]
    assert events[0].ticket.id == "ENG-2"


@pytest.mark.asyncio
async def test_new_comment_emits_ticket_commented():
    adapter = _FakeAdapter({
        "issues": {
            "nodes": [
                _issue_node(
                    identifier="ENG-3",
                    created_at="2026-04-29T08:00:00Z",
                    updated_at="2026-04-30T10:00:05Z",
                    comments=(
                        _comment(id_="c1", body="thoughts?", created_at="2026-04-30T10:00:05Z"),
                    ),
                ),
            ],
            "pageInfo": {"hasNextPage": False},
        }
    })
    events, _ = await adapter.poll_changes(
        since_iso="2026-04-30T10:00:00Z", team_keys=("ENG",),
    )
    types = [e.type for e in events]
    # Issue updated AND a new comment — both fire.
    assert "ticket.updated" in types
    assert "ticket.commented" in types


@pytest.mark.asyncio
async def test_self_authored_comment_is_dropped():
    adapter = _FakeAdapter({
        "issues": {
            "nodes": [
                _issue_node(
                    identifier="ENG-4",
                    created_at="2026-04-29T08:00:00Z",
                    updated_at="2026-04-30T10:00:05Z",
                    comments=(
                        _comment(
                            id_="c1",
                            body="my plan…\n\n<!-- coii-bot -->\n",
                            created_at="2026-04-30T10:00:05Z",
                        ),
                    ),
                ),
            ],
            "pageInfo": {"hasNextPage": False},
        }
    })
    events, _ = await adapter.poll_changes(
        since_iso="2026-04-30T10:00:00Z", team_keys=("ENG",),
    )
    types = [e.type for e in events]
    assert "ticket.commented" not in types
    # Issue update still fires (self-authored filter only applies to comments).
    assert types == ["ticket.updated"]


@pytest.mark.asyncio
async def test_empty_response_returns_unchanged_cursor():
    adapter = _FakeAdapter({
        "issues": {"nodes": [], "pageInfo": {"hasNextPage": False}},
    })
    events, new_cursor = await adapter.poll_changes(
        since_iso="2026-04-30T10:00:00Z", team_keys=("ENG",),
    )
    assert events == []
    assert new_cursor == "2026-04-30T10:00:00Z"


class _MultiQueryAdapter(LinearAdapter):
    """Returns different responses for the issues vs orphan-comments query.

    The fake matches on the operation name in the GraphQL query string —
    ``PollIssues`` vs ``PollOrphanComments`` — so we can simulate Linear
    not bumping ``issue.updatedAt`` on a comment add.
    """

    def __init__(self, issues_resp: dict[str, Any], comments_resp: dict[str, Any]) -> None:
        super().__init__(api_key="fake")
        self._issues = issues_resp
        self._comments = comments_resp

    async def _gql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if "PollOrphanComments" in query:
            return self._comments
        if "PollIssues" in query:
            return self._issues
        raise AssertionError(f"unexpected query: {query[:60]!r}")


@pytest.mark.asyncio
async def test_orphan_comment_surfaces_when_issue_updatedat_didnt_bump():
    """Comment added to an un-updated issue still emits ticket.commented.

    Linear empirically does NOT bump ``issue.updatedAt`` when a comment is
    added; the second top-level comments query is what surfaces it.
    """
    adapter = _MultiQueryAdapter(
        issues_resp={"issues": {"nodes": [], "pageInfo": {"hasNextPage": False}}},
        comments_resp={"comments": {"nodes": [{
            "id": "c-orphan",
            "body": "thoughts?",
            "createdAt": "2026-04-30T10:00:05Z",
            "user": {"id": "u1", "name": "Alice", "displayName": "Alice"},
            "issue": _issue_node(
                identifier="ENG-9",
                created_at="2026-04-29T08:00:00Z",
                updated_at="2026-04-29T08:00:00Z",  # before cursor — not in pass 1
            ),
        }]}},
    )
    events, cursor = await adapter.poll_changes(
        since_iso="2026-04-30T10:00:00Z", team_keys=("ENG",),
    )
    types = [e.type for e in events]
    assert types == ["ticket.commented"]
    assert events[0].ticket.id == "ENG-9"
    assert events[0].actor == "Alice"
    assert cursor == "2026-04-30T10:00:05Z"


@pytest.mark.asyncio
async def test_orphan_comment_dedups_against_nested():
    """A comment that appears in BOTH queries is only emitted once."""
    nested_comment = _comment(
        id_="c-shared", body="hi", created_at="2026-04-30T10:00:05Z",
    )
    adapter = _MultiQueryAdapter(
        issues_resp={"issues": {"nodes": [_issue_node(
            identifier="ENG-10",
            created_at="2026-04-29T08:00:00Z",
            updated_at="2026-04-30T10:00:05Z",  # bumped → pass 1 emits it
            comments=(nested_comment,),
        )], "pageInfo": {"hasNextPage": False}}},
        comments_resp={"comments": {"nodes": [{
            **nested_comment,
            "issue": _issue_node(
                identifier="ENG-10",
                created_at="2026-04-29T08:00:00Z",
                updated_at="2026-04-30T10:00:05Z",
            ),
        }]}},
    )
    events, _ = await adapter.poll_changes(
        since_iso="2026-04-30T10:00:00Z", team_keys=("ENG",),
    )
    # ticket.updated (issue) + exactly ONE ticket.commented (de-duped)
    assert [e.type for e in events] == ["ticket.updated", "ticket.commented"]


@pytest.mark.asyncio
async def test_no_team_keys_returns_empty_without_query():
    """Don't call the API at all if there's nothing to filter on."""
    class _ExplodingAdapter(LinearAdapter):
        def __init__(self):
            super().__init__(api_key="x")
        async def _gql(self, query, variables):
            raise AssertionError("should not have called GraphQL")

    adapter = _ExplodingAdapter()
    events, cursor = await adapter.poll_changes(
        since_iso="2026-04-30T10:00:00Z", team_keys=(),
    )
    assert events == []
    assert cursor == "2026-04-30T10:00:00Z"


# ---------------------------------------------------------------------------
# Poller cursor persistence
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_coii(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("COII_ROOT", str(tmp_path / "coii"))
    return tmp_path / "coii"


def test_save_and_load_cursor(fake_coii: Path):
    poller._save_cursor("2026-04-30T11:00:00Z")
    state_file = fake_coii / "state" / "linear_poller.json"
    assert state_file.is_file()
    data = json.loads(state_file.read_text())
    assert data == {"cursor": "2026-04-30T11:00:00Z"}
    assert poller._load_cursor() == "2026-04-30T11:00:00Z"


def test_load_cursor_missing_returns_none(fake_coii: Path):
    assert poller._load_cursor() is None


def test_load_cursor_corrupt_returns_none(fake_coii: Path):
    state_file = fake_coii / "state" / "linear_poller.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("not json")
    assert poller._load_cursor() is None
