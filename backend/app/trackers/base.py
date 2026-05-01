"""TrackerAdapter ABC — Agent code never imports a concrete tracker."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.trackers.types import Ticket, TicketEvent, TrackerName


class TrackerAdapter(ABC):
    name: TrackerName

    @abstractmethod
    def parse_webhook(
        self,
        raw_body: bytes,
        signature: str | None,
    ) -> TicketEvent | None:
        """Verify signature, decode payload, return a unified event.

        Returns None for events we don't care about (heartbeats, unsupported types).
        Raises on signature failure or malformed payload.
        """

    @abstractmethod
    async def post_comment(self, ticket_id: str, body: str) -> None: ...

    @abstractmethod
    async def get_ticket(self, ticket_id: str) -> Ticket: ...

    async def set_status(self, ticket_id: str, status: str) -> None:  # optional
        raise NotImplementedError

    async def set_assignee(self, ticket_id: str, user_id: str) -> None:  # optional
        raise NotImplementedError
