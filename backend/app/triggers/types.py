"""Trigger config + matching primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TriggerWhen:
    """Match clause. All present fields must match (AND)."""
    tracker: str | None = None
    event: str | None = None
    assignee: str | None = None
    labels_contain: str | None = None
    labels_all: tuple[str, ...] = ()
    project: str | None = None
    team: str | None = None
    ticket_status: str | None = None
    ticket_status_in: tuple[str, ...] = ()


@dataclass(frozen=True)
class Trigger:
    name: str
    when: TriggerWhen
    agent: str
    workflow: str
    raw: dict[str, Any] = field(default_factory=dict)
