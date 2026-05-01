# Loop

Executed on trigger activation. At activation time the backend has already injected: full ticket info + which trigger fired + the workflow prompt for that trigger.

## Default phase flow (when workflow doesn't override)

### Phase 1: Plan
- Read the ticket
- memory_search for similar tickets
- Post a plan comment on the ticket
- Wait for human to reply "go" / "proceed"

### Phase 2: Implement
- Create branch coder/<ticket-id>-<slug>
- Write code → lint → test
- Commit (Conventional Commits)

### Phase 3: Self-review
- Pretend to be a senior reviewer seeing the code for the first time
- Check: edge cases, naming, tests, accidental changes
- If issues found, return to Phase 2 (max 2 rounds)

### Phase 4: Submit
- push, open PR, post summary comment on ticket
- Say "ready for review" in the ticket
- Don't change status on my own

## Workflow override
The trigger's workflow field may tell me to skip planning (fully-auto), do review-only, or something else. **The workflow field takes precedence over the default flow.**

## Session end (required for every workflow)
- Append what happened today to memory/<today>.md
