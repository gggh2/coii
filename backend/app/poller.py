"""LinearPoller — gateway-free alternative to webhooks.

Polls Linear's GraphQL API on a fixed interval, normalizes changes into the
same `TicketEvent` shape the webhook path produces, and feeds them through
``activities.handle_event.dispatch_event``. From there everything is
identical to the webhook flow (matcher → trigger → agent activation).

Cursor persistence
------------------
The high-water mark of the latest seen ``updatedAt`` (across issues and
comments) is stored at ``~/.coii/state/linear_poller.json``. Each poll
fetches strictly newer events, then bumps the cursor on success. If a
poll fails the cursor stays put, so we re-process the next time around
rather than dropping events.

Why no comment-id dedup
-----------------------
We rely on monotonic ``createdAt`` cursors and the strict-greater-than
filter (``> cursor``) for both issues and comments. As long as Linear
clocks are monotonic per-resource (which they are), no event is processed
twice. Boundary equality (cursor == createdAt) is not possible because
we initialize the cursor to "now" on first run and only ever advance.

Bootstrapping
-------------
On first run the cursor is initialized to the current UTC time. We don't
back-fill historical issues; the user wires in polling and forward
events flow from that point. To re-process an old ticket they can edit
it in Linear, which advances ``updatedAt``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.activities.handle_event import dispatch_event, get_linear_adapter
from app.util import coii_root

log = logging.getLogger(__name__)

_STATE_FILENAME = "linear_poller.json"


def _state_path() -> Path:
    return coii_root() / "state" / _STATE_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _load_cursor() -> str | None:
    path = _state_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not read %s: %s — treating as fresh", path, e)
        return None
    return data.get("cursor")


def _save_cursor(cursor: str) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"cursor": cursor}, indent=2) + "\n",
        encoding="utf-8",
    )


class LinearPoller:
    """One Linear poll cycle = one call to ``poll_once()``.

    Hold onto the same instance across the lifecycle so the in-memory
    cursor stays warm; on every cycle the cursor is also flushed to disk.
    """

    def __init__(self, team_keys: tuple[str, ...]) -> None:
        self.team_keys = team_keys
        self.cursor: str | None = _load_cursor()

    async def poll_once(self) -> dict:
        """Run one polling cycle. Returns a stats dict for logs/tests."""
        adapter = get_linear_adapter()
        if not adapter.api_key:
            log.warning("LINEAR_API_KEY not set — skipping poll")
            return {"skipped": "no_api_key"}

        if self.cursor is None:
            # First run: anchor at "now" so we don't replay historical events.
            self.cursor = _now_iso()
            _save_cursor(self.cursor)
            log.info("linear poller first run: anchoring cursor at %s", self.cursor)
            return {"first_run": True, "cursor": self.cursor}

        since = self.cursor
        try:
            events, new_cursor = await adapter.poll_changes(
                since_iso=since, team_keys=self.team_keys,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("linear poll_changes failed (cursor unchanged)")
            return {"error": repr(e), "cursor": since}

        log.info(
            "linear poll: cursor=%s teams=%s -> %d event(s)",
            since, list(self.team_keys), len(events),
        )

        for event in events:
            try:
                await dispatch_event(adapter, event)
            except Exception:  # noqa: BLE001
                # One bad event must not stall the poller. Cursor still advances
                # so we don't loop forever on the same broken payload.
                log.exception(
                    "dispatch failed for ticket=%s type=%s",
                    event.ticket.id, event.type,
                )

        if new_cursor != since:
            self.cursor = new_cursor
            _save_cursor(new_cursor)

        return {
            "cursor_before": since,
            "cursor_after": self.cursor,
            "events": len(events),
        }
