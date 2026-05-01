"""Tests for the <status>...</status> directive parser used by Kanban flows."""

from __future__ import annotations

from app.activities.handle_event import _extract_status_directive


def test_no_directive_returns_unchanged():
    body = "Plain reply with no tag."
    state, reason, cleaned = _extract_status_directive(body)
    assert state is None
    assert reason is None
    assert cleaned == body


def test_simple_directive_strips_and_returns_state():
    body = "Did the work.\n\n<status>Done</status>"
    state, reason, cleaned = _extract_status_directive(body)
    assert state == "Done"
    assert reason is None
    assert cleaned == "Did the work."


def test_directive_with_reason():
    body = "Out of memory while running tests.\n<status>Backlog: OOM in vitest</status>"
    state, reason, cleaned = _extract_status_directive(body)
    assert state == "Backlog"
    assert reason == "OOM in vitest"
    assert cleaned == "Out of memory while running tests."


def test_directive_case_insensitive():
    body = "Working.<STATUS>In Progress</STATUS>"
    state, _, _ = _extract_status_directive(body)
    assert state == "In Progress"


def test_directive_in_middle_of_body_still_extracted():
    body = "Started <status>In Progress</status> and now writing."
    state, _, cleaned = _extract_status_directive(body)
    assert state == "In Progress"
    assert "Started" in cleaned and "writing." in cleaned
    assert "<status>" not in cleaned


def test_state_with_internal_whitespace_preserved():
    body = "Done.<status>  In Progress  </status>"
    state, _, _ = _extract_status_directive(body)
    assert state == "In Progress"


def test_empty_reason_normalized_to_none():
    body = "<status>Backlog:</status>"
    state, reason, _ = _extract_status_directive(body)
    assert state == "Backlog"
    assert reason is None
