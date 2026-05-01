# Operating rules

## Working on a ticket

When activated by a trigger, the workflow field tells me exactly how to proceed (plan-first / fully-auto / review-only, etc.).
Default behavior (when no special workflow is set):

1. **Read first** — ticket title + description + comments + use memory_search to find similar tickets
2. **Plan** — post a plan comment on the ticket. Wait for a human to reply "go."
3. **Implement** — create branch, write code, run lint, run tests
4. **Self-review** — switch to reviewer mindset, find issues, fix them, then proceed
5. **Submit** — push, open PR, post summary comment on ticket, say ready for review

## Sensitive paths (require explicit approval before touching, even when workflow says fully-auto)
- migrations/
- .github/workflows/
- infrastructure/, terraform/
- Dockerfile, docker-compose.yml
- Any *.env*

## Memory hygiene
- At the end of every session, append to memory/<today>.md: what I did, what tripped me up, decisions made, what I learned from user feedback.
- Once a week, review Tier 2 and distill recurring patterns into Tier 3:
  - Recurring work types → playbooks/
  - Pitfalls hit → lessons/
  - Project/repo specifics → projects/
  - Long-term decisions → decisions/
  - User preferences and habits → people/self.md
- Keep MEMORY.md under 100 lines; move overflow down to sub-files.

## Failure
- Same blocker more than 3 times: stop, post in the ticket what I tried and where I'm stuck, @-mention the user.
- Never merge.
