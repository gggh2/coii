"""Verify the runtime dispatch path threads the model spec correctly.

We mock both runtimes so no network is touched. The interesting wiring is
that ``_generate_body`` forwards ``model_spec`` (which originates from a
Agent's ``workspace.json runtime.model``) into ``llm.generate_reply``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.activities.handle_event import _generate_body
from app.trackers.types import Ticket, TicketEvent
from app.triggers.types import Trigger, TriggerWhen


def _evt() -> TicketEvent:
    t = Ticket(
        id="DEMO-1", title="t", description="", status="In Progress",
        assignee=None, labels=(), project=None, team=None,
        url="https://linear.app/x", tracker="linear",
    )
    return TicketEvent(tracker="linear", type="ticket.commented", ticket=t, actor="u")


def _trigger() -> Trigger:
    return Trigger(name="trg", when=TriggerWhen(), agent="coder", workflow="w")


@pytest.mark.asyncio
async def test_llm_direct_forwards_model_spec():
    with patch("app.activities.handle_event.llm.generate_reply",
               new=AsyncMock(return_value="hello from gpt")) as gen, \
         patch("app.activities.handle_event.claude_code.is_available",
               return_value=False):
        out = await _generate_body(
            "llm_direct", "sys", "msg", _trigger(), _evt(),
            model_spec="openai/gpt-4o",
        )
    assert out == "hello from gpt"
    gen.assert_awaited_once()
    kwargs = gen.await_args.kwargs
    assert kwargs["model_spec"] == "openai/gpt-4o"
    assert kwargs["system_prompt"] == "sys"
    assert kwargs["user_message"] == "msg"


@pytest.mark.asyncio
async def test_llm_direct_no_spec_passes_none():
    with patch("app.activities.handle_event.llm.generate_reply",
               new=AsyncMock(return_value="hi")) as gen, \
         patch("app.activities.handle_event.claude_code.is_available",
               return_value=False):
        await _generate_body("llm_direct", "sys", "msg", _trigger(), _evt())
    assert gen.await_args.kwargs["model_spec"] is None


@pytest.mark.asyncio
async def test_auto_falls_back_to_llm_with_spec():
    # claude_code unavailable → auto picks llm_direct, must still carry spec.
    with patch("app.activities.handle_event.llm.generate_reply",
               new=AsyncMock(return_value="ok")) as gen, \
         patch("app.activities.handle_event.llm.is_available", return_value=True), \
         patch("app.activities.handle_event.claude_code.is_available",
               return_value=False):
        await _generate_body(
            "auto", "sys", "msg", _trigger(), _evt(),
            model_spec="anthropic/claude-opus-4-7",
        )
    assert gen.await_args.kwargs["model_spec"] == "anthropic/claude-opus-4-7"


@pytest.mark.asyncio
async def test_template_fallback_when_no_runtime_available():
    # Neither runtime available → confirmation template.
    with patch("app.activities.handle_event.llm.is_available", return_value=False), \
         patch("app.activities.handle_event.claude_code.is_available",
               return_value=False):
        out = await _generate_body("auto", "sys", "msg", _trigger(), _evt())
    assert "@coder" in out
    assert "Acknowledged" in out
