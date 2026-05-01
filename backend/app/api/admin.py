"""Workspace inspectors — read-only views to help you author workflow files.

Once Linear OAuth is complete, hit GET /admin/linear/inspect to see the actual
project / workflow-state / label / team names in your workspace. Use those
strings verbatim in your `*_workflow.yaml` files under `workflows/`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.activities.handle_event import get_linear_adapter

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

INSPECT_QUERY = """
query Inspect {
  organization { name urlKey }
  teams { nodes { id name key
    states { nodes { id name type } }
  } }
  projects { nodes { id name state } }
  issueLabels { nodes { id name team { name } } }
  viewer { id name email }
}
"""


@router.get("/linear/inspect")
async def linear_inspect():
    adapter = get_linear_adapter()
    if not adapter.api_key:
        raise HTTPException(
            400,
            "No LINEAR_API_KEY. Generate one at https://linear.app/settings/api "
            "and put it in services/coii/.env.local_deploy.",
        )
    try:
        data = await adapter._gql(INSPECT_QUERY, {})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Linear GraphQL failed: {e}")

    out = {
        "organization": data.get("organization"),
        "viewer": data.get("viewer"),
        "teams": [
            {
                "key": t["key"],
                "name": t["name"],
                "id": t["id"],
                "states": [
                    {"name": s["name"], "type": s["type"]}
                    for s in (t.get("states") or {}).get("nodes", [])
                ],
            }
            for t in (data.get("teams") or {}).get("nodes", [])
        ],
        "projects": [
            {"name": p["name"], "state": p.get("state")}
            for p in (data.get("projects") or {}).get("nodes", [])
        ],
        "labels": [
            {"name": lbl["name"], "team": (lbl.get("team") or {}).get("name")}
            for lbl in (data.get("issueLabels") or {}).get("nodes", [])
        ],
        "_hint": (
            "Use the exact strings above in your workflow files under "
            "~/.coii/workflows/*_workflow.yaml. "
            "labels go into labels_contain / labels_all; project names into project; "
            "state names into ticket_status / ticket_status_in; team names into team."
        ),
    }
    return out
