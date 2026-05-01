"""Pure trigger matching — TicketEvent + [Trigger] → list[Trigger] in declaration order.

All conditions inside `when` are AND. Multiple triggers can match the same
event (e.g. label-driven AND status-driven both fire). We return them in the
order they appear across the loaded workflow files; caller decides what to
do (Phase 1: fire all of them).
"""

from __future__ import annotations

from app.trackers.types import TicketEvent
from app.triggers.types import Trigger, TriggerWhen


def match(event: TicketEvent, triggers: list[Trigger]) -> list[Trigger]:
    return [t for t in triggers if _matches(event, t.when)]


def _matches(event: TicketEvent, when: TriggerWhen) -> bool:
    t = event.ticket
    if when.tracker is not None and when.tracker != event.tracker:
        return False
    if when.event is not None and when.event != event.type:
        return False
    if when.assignee is not None and when.assignee != t.assignee:
        return False
    if when.labels_contain is not None and when.labels_contain not in t.labels:
        return False
    if when.labels_all and not all(lbl in t.labels for lbl in when.labels_all):
        return False
    if when.project is not None and when.project != t.project:
        return False
    if when.team is not None and when.team != t.team:
        return False
    if when.ticket_status is not None and when.ticket_status != t.status:
        return False
    if when.ticket_status_in and t.status not in when.ticket_status_in:
        return False
    return True
