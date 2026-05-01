# Conversation state & long-running ticket handling

This doc records the design for how a Specialist agent's conversation state
persists across activations on the same ticket — and the tradeoffs we
explicitly accepted.

## TL;DR

**Linear is the durable conversation log. Each activation reads it fresh.**
We do *not* keep a persistent claude session, an internal event store, or a
local conversation cache. The agent runs as a one-shot process per
activation; the prompt includes the full Linear comment history (including
the agent's own past replies) so it has continuity without session state.

## Definitions

- **Activation**: one webhook event triggers one run of the Specialist
  (one `claude` CLI invocation), end to end. See `handle_event.py`
  `_fire_trigger`.
- **Workspace**: per-ticket directory at `~/.workforce/tickets/<id>/`.
  Persistent across activations, cache only — never source of truth.
- **Conversation log**: the ordered sequence of comments on the Linear
  ticket, including ones the agent posted itself.

## Scenario coverage

What the design has to handle, and what we do for each:

| Scenario | Behavior |
|---|---|
| Single activation completes, posts a comment | Works as today: stdout → comment, with `<status>` directive parsing. |
| Multi-turn back-and-forth on the same ticket | Each new event fires a fresh activation; agent reads the full comment history (including its own prior replies) and continues from there. |
| Server down while user comments | Comments persist in Linear. Webhooks for the down period are lost (Linear's retry budget is bounded). Reconciler (deferred) will pick these up. Even without it, the *next* webhook that does land will pull full history and see everything that accumulated. |
| Mac mini disk dies / workspace lost | Conversation history reconstructible from Linear. Code work-products are gone unless agent committed/posted them — see "Open issues" below. |
| User comments while agent is mid-activation | Currently no concurrency guard — the new comment fires a second activation in parallel. Inbox queue (deferred) will fix this. |
| User wants to abort | No mechanism today. Deferred: `agent:abort` label as hard-cancel signal. |

## Why Linear-as-log over a persistent claude session

We considered using `claude --resume <session-id>` to keep a per-ticket
claude session alive across activations. We rejected it. The reasoning:

1. **Redundant storage.** The conversation already exists in Linear in a
   form humans can read. Adding a parallel session file means two copies
   that can drift, plus a new failure mode (session file lost or
   corrupted).
2. **Linear is more durable.** Cloud-hosted, audit-logged, accessible
   without the Mac mini being up. A local session file evaporates if the
   machine dies.
3. **Cross-machine portability.** Linear-as-log means the agent could move
   to a different host without state migration.
4. **Human inspectability.** Engineers can read the full conversation by
   scrolling the Linear ticket. There's no opaque session file to
   debug.
5. **Session resume's only real benefit — token caching of long shared
   prefixes — doesn't survive `--no-session-persistence` anyway and
   isn't needed at our current scale.

## Tradeoffs we accepted

### 1. Prompt size grows linearly with ticket length

Each activation embeds *every* comment. A ticket with 50 turns has a
~50-comment transcript in the prompt. At ~200–500 tokens per comment, a
busy ticket may push 25k+ tokens just for history, plus the system prompt
and ticket metadata.

- **Current threshold**: Claude Sonnet handles 200k+ tokens; not a
  practical limit yet.
- **Cost impact**: linear in turns. A 50-turn ticket costs ~50× a
  single-turn ticket in input tokens.
- **Mitigation if it matters later**: summarize comments older than N
  turns into a single rolling summary block. Keep recent comments
  verbatim. Re-runs only need to re-summarize when N is exceeded, so
  cost stays bounded.

We are *not* implementing the summarization mitigation now — premature.

### 2. Per-activation GraphQL fetch latency

Each activation does one extra `list_comments` call (~100–500ms on
Linear). The activation as a whole takes seconds to minutes (the claude
CLI dominates), so this is in the noise.

### 3. Pagination cap at 100 comments

`list_comments` fetches the most recent 100. Tickets that grow past 100
comments lose their oldest history. Acceptable for now — by the time a
ticket has 100 comments it almost certainly should have been split or
closed.

### 4. Race between comment-create webhook and GraphQL read

The webhook may fire before Linear's read API can see the new comment.
`_render_history` handles this: if the triggering comment isn't in the
fetched list, we append it inline using the body from the webhook
payload, with the same `← TRIGGERING THIS ACTIVATION` marker.

### 5. Self-author detection is heuristic

`is_agent` is detected by string-matching the comment's user fields
against `@oauthapp.linear.app`, `oauth_application`, `app_user`. If
Linear renames these or our app is misidentified, agent-authored
comments will be rendered as if from a human and the agent may
misinterpret its own past replies as user requests. Low-impact, but
worth fixing if false detections show up.

## What we explicitly didn't build (and why)

These are real, valuable features we deliberately deferred. Each is
independently shippable when the pain shows up.

**Priority order if/when we revisit:**
1. **Reconciler cron** — required before production traffic; closes
   the webhook silent-disable hole
2. Inbox queue — required once concurrent comments on the same ticket
   are common
3. Abort label, `--resume`, diff-back-to-Linear — opportunistic

### Inbox queue + per-ticket lock

**Problem**: user comments while the agent is mid-activation. Currently
fires a second activation in parallel; could cause double-work or lost
context.

**Plan**: file lock at `~/.workforce/tickets/<id>/.lock`. New webhook
during a held lock writes to `pending_inbox.jsonl`. Activation, on
exit, drains the inbox and re-fires with all queued events folded into
one prompt. (OpenClaw's `session_inbox` model.)

**Why deferred**: needs the foundation (Linear-as-log) to work first.
Without full-history fetch, an inbox would be re-implementing the same
"recover what the agent missed" logic locally.

### Reconciler cron — **highest-priority deferred item**

**Problem**: Linear's webhook delivery is not durable. Per Linear's
documented policy:

- 3 retry attempts (at +1min, +1hr, +6hr) then permanent drop
- Failure = endpoint unreachable, >5s response, or non-2xx
- Repeated failures cause Linear to **silently disable the webhook
  entirely**, requiring a manual re-enable in workspace settings —
  no notification

So during any backend outage longer than ~7 hours, individual events
are lost forever. Worse, a sustained outage can disable the webhook
permanently, after which everything looks normal but no events fire.

**Partial mitigation already in place**: full-history fetch (this
commit) means *if* any later webhook eventually fires, the agent sees
all the comments that accumulated during the gap. So the system is
self-healing as long as *some* future event lands.

**Remaining hole**: when no future event ever fires — either because
the webhook got disabled and we don't know, or because the user gave
up commenting — the ticket sits with unanswered comments forever.

**Plan**: APScheduler job every ~5 minutes scans Linear for tickets
labeled `agent:specialist-*` in active states. For each, fetch
comments; if the latest comment is not from the agent and no local CLI
is running for that ticket, fire a synthetic activation. As a side
effect, this also detects webhook silent-disable: if the reconciler is
consistently the one finding new work (rather than webhooks), we know
the push channel is broken and can alert.

(Symphony's "reconciliation" / `CanceledByReconciliation` model —
tracker poll as the durable-state backstop, webhooks as the
low-latency hint.)

**Why deferred (revisit before production traffic)**: history-fetch
covers the common case. Reconciler is required before this can be
trusted with real work — webhook silent-disable is a no-notification
failure mode that single-handedly invalidates the system.

### Abort label / hard cancel

**Problem**: user wants to stop a runaway activation.

**Plan**: matcher recognizes `agent:abort` label, kills the active CLI
process for that ticket. Symphony's `CanceledByReconciliation`.

**Why deferred**: rare in practice; the 600s CLI timeout is a backstop.

### Persistent claude session (`--resume`)

**Problem**: cold-start cost on every activation.

**Plan**: per-ticket session id stored in `workspace/session.json`,
`claude --resume <id>` instead of `--no-session-persistence`.

**Why deferred**: see "Why Linear-as-log over a persistent claude
session" above. Don't build until we measure that cold-start is
actually a bottleneck — and even then, prompt-cache improvements may
solve it without session resume.

### Posting code diffs back to Linear

**Problem**: if Mac mini's disk dies, code work-products in workspace
are lost. Linear has only the human-readable summary.

**Plan**: encourage Specialists to include diffs / file contents in
their summary comment via markdown code blocks, or post key files as
attachments. Or: workspace becomes a git repo, push to GitHub on each
activation.

**Why deferred**: most current work fits in a single comment. Real
multi-file refactors would benefit, but that's not the dominant
pattern yet.

## Reference: prior art surveyed

| Project | Session model | Conversation state | Concurrent input | Crash recovery |
|---|---|---|---|---|
| [openai/symphony](https://github.com/openai/symphony) | Persistent thread within a worker lifetime; multi-turn same `thread_id` | Tracker (issue) is source of truth; orchestrator state in-memory | Not supported; reconciliation kills worker if state changes | Re-poll tracker, reuse workspaces |
| [paperclipai/paperclip](https://github.com/paperclipai/paperclip) | "Agents resume the same task context across heartbeats" | Postgres durable store for everything | Atomic task checkout; new input = new event | Direct DB resume |
| [Enderfga/openclaw-claude-code](https://github.com/Enderfga/openclaw-claude-code) | Claude Code: persistent subprocess; others: one-shot | 7-day disk TTL session files | `session_inbox` queue: idle delivers immediately, busy queues | Session auto-resume |

**Common pattern across all three**: tracker / durable store is source of
truth; local agent state is cache; mid-stream user-message injection is
*not* attempted (architecturally hard, low ROI).

Our design takes the same shape with one substitution: instead of
Postgres or local session files as the durable store, we use Linear
itself. This is cheaper, more transparent to humans, and crash-safe.

## Files

- `app/trackers/linear.py` — `LinearAdapter.list_comments()`
- `app/trackers/types.py` — `Comment.is_agent`
- `app/activities/handle_event.py` — `_fetch_history`, `_render_history`,
  `_user_message`
- `tests/test_history_rendering.py` — coverage
