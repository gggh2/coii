"""LinearAdapter — Linear webhooks + GraphQL.

Webhook signature: HMAC-SHA256 of the raw body using LINEAR_WEBHOOK_SECRET,
sent in the `Linear-Signature` header. We compare against the hex digest.

Auth: Linear personal API key in LINEAR_API_KEY (lin_api_*). Generate at
https://linear.app/settings/api. The Authorization header is the raw key
value (Linear does not use the Bearer prefix). OAuth app tokens are not
supported in this build.

This adapter is permissive about which Linear webhook event types it accepts:
Issue, Comment, and AgentSession (Linear's newer agent-platform event) are
all normalized into our four ticket.* event types. Unrecognized events
return None so the controller can no-op them gracefully.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

import httpx

from app.trackers.base import TrackerAdapter
from app.trackers.types import Comment, Ticket, TicketEvent

log = logging.getLogger(__name__)

LINEAR_API = "https://api.linear.app/graphql"

# Hidden marker appended to every comment we post. Lets the webhook + poller
# paths recognize self-authored comments and skip them, preventing
# "bot replies to itself" loops. Markdown HTML comments are not rendered.
_BOT_MARKER = "<!-- coii-bot -->"

# Fields Linear flips automatically when a related entity changes (comment added,
# subscriber count changed, etc.). An Issue.update whose updatedFrom contains only
# these is a side effect of our own activity, not a user-driven change.
_NOISE_UPDATE_FIELDS = frozenset({
    "updatedAt",
    "commentCount",
    "subscriberIds",
    "boardOrder",
    "sortOrder",
    "previousIdentifiers",
    "snoozedUntilAt",
    "trashed",
    "lastAppliedTemplateId",
    "botActor",
    "addedLabelIds",      # connection-only: real change shows up under labelIds
    "removedLabelIds",
})


def _has_meaningful_change(updated_from: dict[str, Any]) -> bool:
    """True if at least one field outside the noise list was changed.

    `updatedFrom` is empty/missing on a fresh create; treat that as a no-op
    here (the create branch has its own path).
    """
    if not updated_from:
        return False
    for key in updated_from.keys():
        if key not in _NOISE_UPDATE_FIELDS:
            return True
    return False


class LinearAdapter(TrackerAdapter):
    name = "linear"

    def __init__(
        self,
        api_key: str | None = None,
        webhook_secret: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("LINEAR_API_KEY") or ""
        self.webhook_secret = webhook_secret or os.getenv("LINEAR_WEBHOOK_SECRET") or ""

    # ----- webhook -----------------------------------------------------------

    def parse_webhook(self, raw_body: bytes, signature: str | None) -> TicketEvent | None:
        if self.webhook_secret:
            self._verify_signature(raw_body, signature)
        else:
            log.warning("LINEAR_WEBHOOK_SECRET not set — skipping signature verification")

        try:
            payload: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError(f"malformed webhook body: {e}") from e

        # Linear sends two webhook shapes in 2025+:
        # 1) Classic: {"action": "create"|"update", "type": "Issue"|"Comment"|...,
        #              "data": {...}, "url": "..."}
        # 2) Agent platform: {"type": "AgentSessionEvent",
        #              "agentSession": {...}, ...} — covered separately.
        type_ = payload.get("type")
        action = payload.get("action")

        if type_ == "Issue":
            return self._issue_event(action, payload)
        if type_ == "Comment":
            return self._comment_event(action, payload)
        if type_ in ("AgentSessionEvent", "AgentSession"):
            return self._agent_session_event(payload)

        log.info("ignoring linear webhook type=%r action=%r", type_, action)
        return None

    def _verify_signature(self, raw_body: bytes, signature: str | None) -> None:
        if not signature:
            raise PermissionError("missing Linear-Signature header")
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise PermissionError("Linear webhook signature mismatch")

    def _issue_event(self, action: str | None, payload: dict[str, Any]) -> TicketEvent | None:
        data = payload.get("data") or {}
        ticket = self._ticket_from_issue_data(data, payload)
        actor = (payload.get("actor") or {}).get("name") or (payload.get("actor") or {}).get("email")

        if action == "create":
            return TicketEvent(
                tracker="linear", type="ticket.created", ticket=ticket, actor=actor, raw=payload,
            )
        if action == "update":
            updated_from = payload.get("updatedFrom") or {}
            if "assigneeId" in updated_from:
                return TicketEvent(
                    tracker="linear", type="ticket.assigned",
                    ticket=ticket, actor=actor, raw=payload,
                )
            # Linear refires Issue.update when a comment is added (commentCount /
            # updatedAt change). If no user-meaningful field changed, skip — otherwise
            # every comment we post causes an Issue.update that re-fires triggers like
            # `labels_contain: agent:coder` and we recurse forever.
            if not _has_meaningful_change(updated_from):
                log.info("ignoring Issue.update with no meaningful change: %s",
                         sorted(updated_from.keys()))
                return None
            return TicketEvent(
                tracker="linear", type="ticket.updated", ticket=ticket, actor=actor, raw=payload,
            )
        if action == "remove":
            return None
        return None

    def _comment_event(self, action: str | None, payload: dict[str, Any]) -> TicketEvent | None:
        if action != "create":
            return None
        data = payload.get("data") or {}
        # Drop comments authored by the OAuth app itself, otherwise every
        # comment we post triggers a webhook that fires us again forever.
        # Check several places Linear stamps the actor identity.
        if self._is_self_authored(data, payload):
            log.info("ignoring self-authored comment on ticket %s", (data.get("issue") or {}).get("identifier"))
            return None
        user = data.get("user") or {}
        issue = data.get("issue") or {}
        ticket = self._ticket_from_issue_data(issue, payload)
        actor = user.get("name") or user.get("email")
        return TicketEvent(
            tracker="linear", type="ticket.commented",
            ticket=ticket, actor=actor, raw=payload,
        )

    def _is_self_authored(self, data: dict[str, Any], payload: dict[str, Any]) -> bool:
        """True if the comment was posted by us (i.e. tagged with `_BOT_MARKER`).

        With personal API keys the bot's posts carry the user's identity (no
        ``oauthapp.linear.app`` footer to filter on), so the only reliable
        self-author signal is a marker we add ourselves in ``post_comment``.
        Markdown HTML comments are invisible to humans in Linear's renderer.
        """
        body = data.get("body") or ""
        return _BOT_MARKER in body

    def _agent_session_event(self, payload: dict[str, Any]) -> TicketEvent | None:
        # Linear's agent platform fires AgentSession events when an app gets
        # mentioned/assigned. We collapse them into ticket.assigned so trigger
        # rules stay tracker-agnostic. Caller can drill into payload via raw.
        session = payload.get("agentSession") or payload.get("data") or {}
        issue = session.get("issue") or {}
        if not issue:
            return None
        ticket = self._ticket_from_issue_data(issue, payload)
        actor = ((session.get("creator") or {}).get("name")) \
            or ((session.get("creator") or {}).get("email"))
        return TicketEvent(
            tracker="linear", type="ticket.assigned",
            ticket=ticket, actor=actor, raw=payload,
        )

    def _ticket_from_issue_data(
        self, data: dict[str, Any], payload: dict[str, Any],
    ) -> Ticket:
        # Webhook bodies sometimes flatten; sometimes nest. Be defensive.
        labels_field = data.get("labels") or []
        if isinstance(labels_field, dict):  # GraphQL connection shape
            labels_field = labels_field.get("nodes") or []
        labels = tuple(
            (l.get("name") if isinstance(l, dict) else str(l))
            for l in labels_field
            if l
        )

        state = data.get("state") or {}
        status = state.get("name") if isinstance(state, dict) else (data.get("stateName") or "")

        assignee_obj = data.get("assignee") or {}
        if isinstance(assignee_obj, dict):
            assignee = (
                assignee_obj.get("name")
                or assignee_obj.get("email")
                or assignee_obj.get("id")
            )
        else:
            assignee = data.get("assigneeName") or data.get("assigneeId")

        project_obj = data.get("project") or {}
        project = project_obj.get("name") if isinstance(project_obj, dict) else None

        team_obj = data.get("team") or {}
        team = team_obj.get("name") if isinstance(team_obj, dict) else None

        url = (
            data.get("url")
            or payload.get("url")
            or f"https://linear.app/issue/{data.get('identifier') or data.get('id') or ''}"
        )

        return Ticket(
            id=data.get("identifier") or data.get("id") or "",
            title=data.get("title") or "",
            description=data.get("description") or "",
            status=status or "",
            assignee=assignee,
            labels=labels,
            project=project,
            team=team,
            url=url,
            tracker="linear",
            raw=data,
        )

    # ----- GraphQL writes ----------------------------------------------------

    async def post_comment(self, ticket_id: str, body: str) -> None:
        # Linear `commentCreate` accepts an issueId (UUID) OR identifier (e.g. ENG-12).
        # We resolve identifier -> UUID first to keep the mutation simple.
        # Append the bot marker so the next webhook/poll cycle recognizes this
        # comment as ours and skips it instead of re-firing triggers.
        issue_uuid = await self._resolve_issue_uuid(ticket_id)
        marked = body.rstrip() + "\n\n" + _BOT_MARKER + "\n"
        mutation = """
        mutation CommentCreate($input: CommentCreateInput!) {
          commentCreate(input: $input) { success comment { id } }
        }
        """
        await self._gql(
            mutation,
            {"input": {"issueId": issue_uuid, "body": marked}},
        )

    async def set_status(self, ticket_id: str, status: str) -> None:
        # Resolve issue + state name → state ID, then update.
        issue_uuid = await self._resolve_issue_uuid(ticket_id)
        team_id = await self._team_id_for_issue(issue_uuid)
        state_id = await self._state_id(team_id, status)
        mutation = """
        mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
          issueUpdate(id: $id, input: $input) { success }
        }
        """
        await self._gql(mutation, {"id": issue_uuid, "input": {"stateId": state_id}})

    async def list_comments(self, ticket_id: str) -> list[Comment]:
        """Fetch all comments on a ticket, oldest-first.

        Used by handle_event to feed the full conversation history into every
        activation's prompt. This is the durable conversation log — Linear
        owns it, the agent reads it, no local session state needed.

        Pagination: capped at 100 most-recent comments. Tickets that grow past
        that lose their oldest comments — acceptable for now; if it becomes a
        real problem we can summarize older history or paginate.

        is_agent is set when the comment looks like it came from our OAuth
        app (same heuristic as the inbound-webhook self-author filter).
        """
        query = """
        query IssueComments($id: String!) {
          issue(id: $id) {
            comments(first: 100) {
              nodes {
                id body createdAt
                user { id name email displayName }
              }
            }
          }
        }
        """
        data = await self._gql(query, {"id": ticket_id})
        issue = data.get("issue") or {}
        nodes = ((issue.get("comments") or {}).get("nodes")) or []
        out: list[Comment] = []
        for n in nodes:
            user = n.get("user") or {}
            author = (
                user.get("displayName") or user.get("name") or user.get("email") or "unknown"
            )
            out.append(Comment(
                id=n.get("id") or "",
                author=author,
                body=n.get("body") or "",
                created_at=n.get("createdAt") or "",
                is_agent=self._is_self_authored({"user": user, "body": n.get("body") or ""}, {}),
            ))
        # Linear returns newest-first by default; flip so the prompt reads as a
        # natural top-to-bottom transcript.
        out.sort(key=lambda c: c.created_at)
        return out

    # ----- polling (no-gateway alternative to webhooks) ----------------------

    async def poll_changes(
        self, *, since_iso: str, team_keys: tuple[str, ...],
    ) -> tuple[list[TicketEvent], str]:
        """Fetch issues + comments changed since `since_iso`.

        Returns (events, new_cursor_iso). `new_cursor_iso` is the latest
        timestamp seen — caller persists it as the next cursor. If nothing
        changed, returns ([], since_iso).

        Event normalization rules:
          - issue.createdAt > since_iso  → emit ticket.created
          - else, issue.updatedAt > since_iso → emit ticket.updated
          - for each comment with createdAt > since_iso (and not self-authored)
            → emit ticket.commented

        A single issue can produce both a ticket.* event AND one or more
        ticket.commented events in the same poll. Matches webhook semantics
        where issue updates and comment creations are independent webhooks.

        Two GraphQL calls per poll:
          1. ``issues(updatedAt > cursor)`` — issue events plus any nested
             comments on those updated issues.
          2. ``comments(issue.team.key in teamKeys, createdAt > cursor)`` —
             comments on issues that *weren't* updated. Linear does NOT
             bump ``issue.updatedAt`` when a comment is added, so without
             this second query, polling silently drops comments.

        Comments seen via both queries are de-duplicated by comment id so
        the second call doesn't double-emit.

        Per-team filtering so we don't pull from teams the user doesn't
        care about. ``team_keys`` should be the short codes Linear shows
        in ticket IDs (e.g. ENG for ENG-42).
        """
        if not team_keys:
            return [], since_iso

        issues_query = """
        query PollIssues($cursor: DateTimeOrDuration!, $teamKeys: [String!]!) {
          issues(
            filter: {
              team: { key: { in: $teamKeys } }
              updatedAt: { gt: $cursor }
            }
            first: 50
            orderBy: updatedAt
          ) {
            nodes {
              id identifier title description url
              createdAt updatedAt
              state { name }
              assignee { id name email }
              labels { nodes { name } }
              project { name }
              team { name key }
              comments(filter: { createdAt: { gt: $cursor } }, first: 50) {
                nodes {
                  id body createdAt
                  user { id name email displayName }
                }
              }
            }
            pageInfo { hasNextPage }
          }
        }
        """
        comments_query = """
        query PollOrphanComments($cursor: DateTimeOrDuration!, $teamKeys: [String!]!) {
          comments(
            filter: {
              issue: { team: { key: { in: $teamKeys } } }
              createdAt: { gt: $cursor }
            }
            first: 50
            orderBy: createdAt
          ) {
            nodes {
              id body createdAt
              user { id name email displayName }
              issue {
                id identifier title description url
                createdAt updatedAt
                state { name }
                assignee { id name email }
                labels { nodes { name } }
                project { name }
                team { name key }
              }
            }
          }
        }
        """

        variables = {"cursor": since_iso, "teamKeys": list(team_keys)}
        issues_data = await self._gql(issues_query, variables)
        comments_data = await self._gql(comments_query, variables)

        events: list[TicketEvent] = []
        max_seen = since_iso
        seen_comment_ids: set[str] = set()

        # ── Pass 1: issues that were updated (plus their nested comments).
        for node in ((issues_data.get("issues") or {}).get("nodes")) or []:
            ticket = self._ticket_from_issue_data(node, {})
            updated_at = node.get("updatedAt") or ""
            created_at = node.get("createdAt") or ""
            if updated_at > max_seen:
                max_seen = updated_at

            if created_at and created_at > since_iso:
                events.append(TicketEvent(
                    tracker="linear", type="ticket.created",
                    ticket=ticket, actor=None, raw=node,
                ))
            elif updated_at and updated_at > since_iso:
                events.append(TicketEvent(
                    tracker="linear", type="ticket.updated",
                    ticket=ticket, actor=None, raw=node,
                ))

            for cn in ((node.get("comments") or {}).get("nodes")) or []:
                cid = cn.get("id") or ""
                if cid:
                    seen_comment_ids.add(cid)
                if self._is_self_authored({"user": cn.get("user") or {},
                                           "body": cn.get("body") or ""}, {}):
                    continue
                user = cn.get("user") or {}
                actor = user.get("displayName") or user.get("name") or user.get("email")
                events.append(TicketEvent(
                    tracker="linear", type="ticket.commented",
                    ticket=ticket, actor=actor, raw=cn,
                ))
                c_at = cn.get("createdAt") or ""
                if c_at > max_seen:
                    max_seen = c_at

        # ── Pass 2: orphan comments (issue not in pass 1 because its
        # updatedAt didn't change). Skip ones we already emitted.
        for cn in ((comments_data.get("comments") or {}).get("nodes")) or []:
            cid = cn.get("id") or ""
            if cid and cid in seen_comment_ids:
                continue
            if self._is_self_authored({"user": cn.get("user") or {},
                                       "body": cn.get("body") or ""}, {}):
                continue
            issue_node = cn.get("issue") or {}
            if not issue_node:
                continue
            ticket = self._ticket_from_issue_data(issue_node, {})
            user = cn.get("user") or {}
            actor = user.get("displayName") or user.get("name") or user.get("email")
            events.append(TicketEvent(
                tracker="linear", type="ticket.commented",
                ticket=ticket, actor=actor, raw=cn,
            ))
            c_at = cn.get("createdAt") or ""
            if c_at > max_seen:
                max_seen = c_at

        return events, max_seen

    async def get_ticket(self, ticket_id: str) -> Ticket:
        query = """
        query Issue($id: String!) {
          issue(id: $id) {
            id identifier title description url
            state { name }
            assignee { id name email }
            labels { nodes { name } }
            project { name }
            team { name }
          }
        }
        """
        data = await self._gql(query, {"id": ticket_id})
        node = data["issue"]
        return self._ticket_from_issue_data(node, {})

    # ----- internals ---------------------------------------------------------

    async def _gql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("LINEAR_API_KEY not set — cannot call Linear GraphQL")
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                LINEAR_API,
                headers={
                    "Authorization": self.api_key,
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": variables},
            )
        try:
            body = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise
        if body.get("errors"):
            raise RuntimeError(f"Linear GraphQL error: {body['errors']}")
        if resp.status_code >= 400:
            raise RuntimeError(f"Linear HTTP {resp.status_code}: {body}")
        return body["data"]

    async def _resolve_issue_uuid(self, ticket_id: str) -> str:
        # Already a UUID? (best-effort heuristic — UUIDs have hyphens and len 36)
        if len(ticket_id) == 36 and ticket_id.count("-") == 4:
            return ticket_id
        query = """
        query Issue($id: String!) { issue(id: $id) { id } }
        """
        data = await self._gql(query, {"id": ticket_id})
        return data["issue"]["id"]

    async def _team_id_for_issue(self, issue_uuid: str) -> str:
        query = """
        query Issue($id: String!) { issue(id: $id) { team { id } } }
        """
        data = await self._gql(query, {"id": issue_uuid})
        return data["issue"]["team"]["id"]

    async def _state_id(self, team_id: str, name: str) -> str:
        query = """
        query States($teamId: ID!) {
          workflowStates(filter: { team: { id: { eq: $teamId } } }) {
            nodes { id name }
          }
        }
        """
        data = await self._gql(query, {"teamId": team_id})
        for s in data["workflowStates"]["nodes"]:
            if s["name"].lower() == name.lower():
                return s["id"]
        raise ValueError(f"no state named {name!r} in team {team_id}")
