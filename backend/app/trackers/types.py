"""Tracker-agnostic data types. Linear/Jira adapters normalize into these.

Design note: status / labels / project / assignee stay as raw strings.
We do not map them. Different users name things differently — let the
Agent's prompt interpret semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

TrackerName = Literal["linear", "jira"]
EventType = Literal[
    "ticket.created",
    "ticket.updated",
    "ticket.commented",
    "ticket.assigned",
]


@dataclass(frozen=True)
class Comment:
    id: str
    author: str
    body: str
    created_at: str  # ISO-8601
    is_agent: bool = False  # authored by our integration (OAuth app)


@dataclass(frozen=True)
class Ticket:
    id: str
    title: str
    description: str
    status: str
    assignee: str | None
    labels: tuple[str, ...]
    project: str | None
    team: str | None
    url: str
    tracker: TrackerName
    raw: dict[str, Any] = field(default_factory=dict)
    comments: tuple[Comment, ...] = ()


@dataclass(frozen=True)
class TicketEvent:
    tracker: TrackerName
    type: EventType
    ticket: Ticket
    actor: str | None  # who triggered this (user / app)
    raw: dict[str, Any] = field(default_factory=dict)
