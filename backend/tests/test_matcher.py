"""Trigger matcher unit tests — isolated from Linear / FS."""

from __future__ import annotations

from app.trackers.types import Ticket, TicketEvent
from app.triggers.matcher import match
from app.triggers.types import Trigger, TriggerWhen


def _ticket(**overrides) -> Ticket:
    base = dict(
        id="ENG-1",
        title="t",
        description="",
        status="Todo",
        assignee=None,
        labels=(),
        project=None,
        team=None,
        url="https://x",
        tracker="linear",
        raw={},
        comments=(),
    )
    base.update(overrides)
    return Ticket(**base)


def _event(t: Ticket, type_: str = "ticket.updated") -> TicketEvent:
    return TicketEvent(tracker="linear", type=type_, ticket=t, actor="alice", raw={})


def test_label_trigger_matches():
    trig = Trigger(
        name="label",
        when=TriggerWhen(tracker="linear", event="ticket.updated", labels_contain="agent:coder"),
        agent="coder",
        workflow="plan",
    )
    e = _event(_ticket(labels=("agent:coder", "bug")))
    assert [t.name for t in match(e, [trig])] == ["label"]


def test_project_trigger_does_not_match_wrong_project():
    trig = Trigger(
        name="proj",
        when=TriggerWhen(tracker="linear", event="ticket.assigned", project="Sandbox"),
        agent="coder",
        workflow="full-auto",
    )
    e = _event(_ticket(project="Other"), type_="ticket.assigned")
    assert match(e, [trig]) == []


def test_status_trigger_matches_exact():
    trig = Trigger(
        name="status",
        when=TriggerWhen(tracker="linear", event="ticket.updated", ticket_status="Needs Review"),
        agent="coder",
        workflow="review",
    )
    e = _event(_ticket(status="Needs Review"))
    assert [t.name for t in match(e, [trig])] == ["status"]


def test_status_in_list_matches_any():
    trig = Trigger(
        name="any-status",
        when=TriggerWhen(
            tracker="linear", event="ticket.updated",
            ticket_status_in=("Todo", "Backlog"),
        ),
        agent="coder",
        workflow="x",
    )
    e = _event(_ticket(status="Backlog"))
    assert [t.name for t in match(e, [trig])] == ["any-status"]


def test_multiple_triggers_can_match_in_order():
    t1 = Trigger(
        name="first", agent="coder", workflow="a",
        when=TriggerWhen(tracker="linear", event="ticket.updated"),
    )
    t2 = Trigger(
        name="second", agent="coder", workflow="b",
        when=TriggerWhen(tracker="linear", event="ticket.updated", labels_contain="x"),
    )
    e = _event(_ticket(labels=("x",)))
    names = [t.name for t in match(e, [t1, t2])]
    assert names == ["first", "second"]


def test_AND_semantics_within_when():
    """All present fields must match (AND)."""
    trig = Trigger(
        name="combined",
        when=TriggerWhen(
            tracker="linear",
            event="ticket.assigned",
            project="Sandbox",
            labels_contain="ready",
        ),
        agent="coder",
        workflow="x",
    )
    matches = match(_event(_ticket(project="Sandbox", labels=("ready",)), "ticket.assigned"), [trig])
    assert len(matches) == 1
    # Missing one condition — no match
    assert match(_event(_ticket(project="Other", labels=("ready",)), "ticket.assigned"), [trig]) == []
    assert match(_event(_ticket(project="Sandbox", labels=()), "ticket.assigned"), [trig]) == []
