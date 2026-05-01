# coii

Turn a Linear ticket into a conversation with an AI agent.

Mention `@coder` on a Linear ticket and a markdown-defined Agent — its
own identity, memory, and tools — drafts a reply and posts it back.
Bring your own LLM key (Anthropic or OpenAI), bring your own Linear
workspace, run it on your own machine. No OAuth, no hosted service, no
data leaving your laptop.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/gggh2/coii/main/install.sh | bash
```

The installer pulls `uv` if missing, installs the `coii` CLI, and drops
you into an interactive setup wizard that walks through:

1. **LLM provider** — pick Anthropic or OpenAI, paste your API key, pick
   a default model.
2. **Linear** — paste your personal API key, pick your team key
   (e.g. `ENG`).
3. **Service** — pick a log level.

The wizard writes secrets to `~/.coii/.env` (mode 0600) and structured
config to `~/.coii/config.json`, and seeds `~/.coii/` with a default
agent + workflow.

Then start the backend:

```bash
coii serve        # FastAPI on :3001
```

Mention `@coder` on a Linear ticket in your team — the poller picks it
up on the next interval and the agent replies.

## Reconfigure later

Two ways to change config after install:

```bash
coii setup --wizard                  # re-run the same flow; merges, never clobbers
coii config set models.default openai/gpt-4o
coii config get trackers.linear.team_keys
coii config validate
```

`coii config --help` lists the rest (`file`, `unset`, `audit`).
Secrets in `config.json` are stored as `SecretRef` pointers
(`{"source": "env", "id": "ANTHROPIC_API_KEY"}`) — the actual values
live in `~/.coii/.env`, so the JSON is safe to share or diff.

## Tweak the agent

Agents live in `~/.coii/agents/<name>/`. Edit the markdown files to
change identity, voice, or what the agent knows about you — changes are
picked up on the next event without a restart.

```
coder/
├── IDENTITY.md      # who the agent is
├── SOUL.md          # values, voice, principles
├── TOOLS.md         # what it can do
├── USER.md          # what it knows about you
└── workspace.json   # runtime overrides (e.g. pin a different model)
```

Workflows in `~/.coii/workflows/*.yaml` map Linear events to agents:

```yaml
name: default_coder
trigger:
  source: linear
  event: comment.create
  match:
    mentions: ["@coder"]
agent: coder
```

## Add an LLM provider

Drop a class into `backend/app/runtimes/providers/` and register it in
`providers/__init__.py`. Anthropic and OpenAI are the bundled examples.

## Layout

```
coii/
├── install.sh                # one-liner installer
└── backend/app/
    ├── activities/           # business logic (Result-typed)
    ├── api/                  # FastAPI controllers
    ├── runtimes/             # LLM runtime + provider registry
    ├── agents/               # workspace loader
    ├── trackers/             # Linear adapter (GraphQL polling)
    └── triggers/             # YAML workflow loader + matcher
```

`~/.coii/` (outside the repo) holds per-user state: agents, workflows,
memory, and per-ticket workspaces. Never checked in.

## Hacking

```bash
git clone https://github.com/gggh2/coii
cd coii/backend
uv sync
uv run pytest                       # unit + integration tests
./scripts/e2e_all.sh                # install + polling + dispatch e2e (live Linear)
```

E2E suites read keys from `.env.test`; `e2e_dispatch.py` skips cleanly
if no LLM key is configured.

## Credits

Config layer (JSON + `SecretRef` + `.env` separation) is modeled on
[openclaw](https://github.com/openclaw/openclaw).

## License

MIT.
