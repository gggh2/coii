"""Tests for full-history conversation rendering in _user_message.

Covers the Linear-as-conversation-log path: every activation reads the full
comment history and renders it into the agent's user message, including
agent-authored replies and a marker on the comment that triggered THIS run.
"""

from __future__ import annotations

import pytest

from app.activities.handle_event import _render_history, _user_message
from app.trackers.types import Comment, Ticket, TicketEvent
from app.triggers.types import Trigger, TriggerWhen


def _ticket(**overrides) -> Ticket:
    base = dict(
        id="ENG-1",
        title="t",
        description="",
        status="In Progress",
        assignee=None,
        labels=(),
        project=None,
        team=None,
        url="https://linear.app/issue/ENG-1",
        tracker="linear",
        raw={},
    )
    base.update(overrides)
    return Ticket(**base)


def _event(type_="ticket.commented", raw=None) -> TicketEvent:
    return TicketEvent(
        tracker="linear",
        type=type_,
        ticket=_ticket(),
        actor="alice",
        raw=raw or {},
    )


def _trigger() -> Trigger:
    return Trigger(
        name="t1",
        when=TriggerWhen(event="ticket.commented"),
        agent="coder",
        workflow="do the thing",
        raw={},
    )


def test_render_empty_returns_empty_string():
    out = _render_history([], None, None, _event())
    assert out == ""


def test_render_human_only_no_marker_when_id_missing():
    history = [
        Comment(id="c1", author="alice", body="hi", created_at="2026-04-29T10:00:00Z"),
    ]
    out = _render_history(history, None, None, _event())
    assert "Conversation history" in out
    assert "alice" in out and "hi" in out
    assert "TRIGGERING" not in out


def test_render_marks_triggering_entry():
    history = [
        Comment(id="c1", author="alice", body="first", created_at="2026-04-29T10:00:00Z"),
        Comment(id="c2", author="alice", body="second", created_at="2026-04-29T10:05:00Z"),
    ]
    out = _render_history(history, "c2", "second", _event(raw={"data": {"id": "c2", "body": "second"}}))
    # Only the matching entry gets the marker.
    assert out.count("TRIGGERING THIS ACTIVATION") == 1
    # The marker is on the c2 line, not c1.
    before_c2 = out.split("second")[0]
    assert "TRIGGERING" in before_c2
    assert "first" in out


def test_render_agent_comments_labeled_distinctly():
    history = [
        Comment(id="c1", author="alice", body="please do X", created_at="2026-04-29T10:00:00Z"),
        Comment(id="c2", author="agent-bot", body="done — see foo.py",
                created_at="2026-04-29T10:05:00Z", is_agent=True),
    ]
    out = _render_history(history, None, None, _event())
    assert "**you** (agent)" in out
    assert "alice" in out


def test_render_appends_triggering_when_history_lacks_it():
    """Race fallback: the webhook fired before list_comments could see the new comment."""
    history = [
        Comment(id="c1", author="alice", body="old", created_at="2026-04-29T10:00:00Z"),
    ]
    out = _render_history(
        history,
        triggering_id="c-NEW",  # not in history
        triggering_body="brand new comment",
        event=_event(raw={"data": {"id": "c-NEW", "body": "brand new comment"}}),
    )
    assert "old" in out
    assert "brand new comment" in out
    assert out.count("TRIGGERING THIS ACTIVATION") == 1
    # The triggering line should appear AFTER the historical one.
    assert out.index("brand new comment") > out.index("old")


def test_render_no_race_fallback_for_non_comment_events():
    """A ticket.updated event with a triggering_body should NOT inject a fake comment."""
    history = [
        Comment(id="c1", author="alice", body="x", created_at="2026-04-29T10:00:00Z"),
    ]
    out = _render_history(
        history,
        triggering_id="c-other",
        triggering_body="this is a label change body that snuck in",
        event=_event(type_="ticket.updated"),
    )
    assert "this is a label change" not in out


def test_user_message_includes_history_section():
    history = [
        Comment(id="c1", author="alice", body="please add validation",
                created_at="2026-04-29T10:00:00Z"),
        Comment(id="c2", author="agent-bot", body="done",
                created_at="2026-04-29T10:05:00Z", is_agent=True),
    ]
    msg = _user_message(_event(), _trigger(), history)
    assert "## Conversation history" in msg
    assert "please add validation" in msg
    assert "**you** (agent)" in msg
    # Ticket metadata still present.
    assert "ENG-1" in msg
    # Memory-model instruction is present so the agent treats history as memory.
    assert "Memory model" in msg


def test_user_message_with_empty_history_still_renders_ticket():
    msg = _user_message(_event(type_="ticket.created"), _trigger(), [])
    assert "ENG-1" in msg
    # No transcript section when there's nothing to render. The "Memory model"
    # paragraph mentions the phrase in passing, so anchor on the markdown header.
    assert "## Conversation history" not in msg


def test_user_message_history_section_after_workflow_before_task():
    history = [
        Comment(id="c1", author="alice", body="one", created_at="2026-04-29T10:00:00Z"),
    ]
    msg = _user_message(_event(), _trigger(), history)
    workflow_idx = msg.index("Workflow for this activation")
    history_idx = msg.index("Conversation history")
    task_idx = msg.index("Your task")
    assert workflow_idx < history_idx < task_idx
