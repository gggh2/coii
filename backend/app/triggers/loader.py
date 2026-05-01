"""Load workflow files from ~/.coii/workflows/.

Each `*_workflow.yaml` file in the workflows root is a self-contained
workflow definition. Users can add or remove workflow files freely; flip
`enabled: false` at the top of a file to disable it without deleting.

Schema:
    name: my-workflow              # optional, defaults to filename stem
    enabled: true                  # optional, defaults to true
    triggers:
      - name: "..."
        when: { ... }
        agent: coder
        workflow: |
          ...

Triggers from all enabled workflow files are concatenated in filename order
(stable across loads), and within each file in declaration order.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.triggers.types import Trigger, TriggerWhen
from app.util import coii_root

log = logging.getLogger(__name__)

WORKFLOW_GLOB = "*_workflow.yaml"


def load_triggers(path: Path | None = None) -> list[Trigger]:
    """Load triggers from all enabled workflow files in the workflows root.

    `path` (back-compat): if given and points to a single file, only that
    file is loaded — useful for tests that exercise one workflow in isolation.
    """
    if path is not None:
        return _load_one(path)

    root = coii_root() / "workflows"
    files = sorted(root.glob(WORKFLOW_GLOB))
    if not files:
        log.warning(
            "no %s files found under %s — returning []", WORKFLOW_GLOB, root,
        )
        return []

    out: list[Trigger] = []
    for f in files:
        out.extend(_load_one(f))
    log.info("loaded %d triggers from %d workflow file(s)", len(out), len(files))
    return out


def _load_one(path: Path) -> list[Trigger]:
    if not path.exists():
        log.warning("workflow file not found at %s — returning []", path)
        return []

    with path.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}

    workflow_name = doc.get("name") or path.stem
    if doc.get("enabled") is False:
        log.info("workflow %r disabled (enabled: false in %s) — skipping",
                 workflow_name, path.name)
        return []

    raw_triggers = doc.get("triggers") or []
    out: list[Trigger] = []
    for i, raw in enumerate(raw_triggers):
        try:
            out.append(_parse_trigger(raw))
        except (KeyError, TypeError, ValueError) as e:
            log.error("%s entry #%d invalid (%s): %r", path.name, i, e, raw)
    log.info("loaded %d triggers from workflow %r (%s)",
             len(out), workflow_name, path.name)
    return out


def _parse_trigger(raw: dict[str, Any]) -> Trigger:
    when = raw.get("when") or {}
    labels_all = when.get("labels_all") or []
    if isinstance(labels_all, str):
        labels_all = [labels_all]
    status_in = when.get("ticket_status_in") or []
    if isinstance(status_in, str):
        status_in = [status_in]

    return Trigger(
        name=raw["name"],
        when=TriggerWhen(
            tracker=when.get("tracker"),
            event=when.get("event"),
            assignee=when.get("assignee"),
            labels_contain=when.get("labels_contain"),
            labels_all=tuple(labels_all),
            project=when.get("project"),
            team=when.get("team"),
            ticket_status=when.get("ticket_status"),
            ticket_status_in=tuple(status_in),
        ),
        agent=raw["agent"],
        workflow=(raw.get("workflow") or "").strip(),
        raw=raw,
    )
