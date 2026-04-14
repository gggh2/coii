<p align="center">
  <img src="https://raw.githubusercontent.com/coii-dev/coii/main/docs/logo.svg" alt="Coii" width="120" />
</p>

<h1 align="center">Coii</h1>

<p align="center">
  <strong>Open-source LLM A/B testing with real business outcomes.</strong><br />
  Run experiments across models, track cost and conversion in production, and get a plain-English recommendation.
</p>

<p align="center">
  <a href="https://github.com/coii-dev/coii/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License" /></a>
  <a href="https://pypi.org/project/coii-server/"><img src="https://img.shields.io/pypi/v/coii-server.svg" alt="PyPI" /></a>
  <a href="https://pypi.org/project/coii/"><img src="https://img.shields.io/pypi/v/coii?label=sdk" alt="SDK PyPI" /></a>
  <a href="https://github.com/coii-dev/coii/actions"><img src="https://img.shields.io/github/actions/workflow/status/coii-dev/coii/test.yml?label=tests" alt="Tests" /></a>
  <a href="https://pypi.org/project/coii/"><img src="https://img.shields.io/pypi/pyversions/coii.svg" alt="Python 3.11+" /></a>
  <a href="https://coii.dev/discord"><img src="https://img.shields.io/discord/placeholder?label=discord&color=7289da" alt="Discord" /></a>
</p>

<p align="center">
  <a href="https://coii.dev">Website</a> ·
  <a href="https://coii.dev/docs">Docs</a> ·
  <a href="https://coii.dev/discord">Discord</a> ·
  <a href="https://github.com/coii-dev/coii/issues">Issues</a>
</p>

---

```
┌───────────────────────┬─────────────┬────────────────┬─────────────┐
│                       │ GPT-4o      │ Claude Sonnet  │ Gemini Flash │
│                       │ (current)   │ (challenger)   │ (challenger) │
├───────────────────────┼─────────────┼────────────────┼─────────────┤
│ Users                 │ 1,441       │ 481            │ 480         │
│ Ticket resolution     │ 72%         │ 78% ✓ +8.3%   │ 65%         │
│ Escalation rate       │ 18%         │ 14%            │ 24%         │
│ Avg latency           │ 1.2s        │ 0.9s           │ 0.3s        │
│ Avg cost / request    │ $0.0034     │ $0.0041        │ $0.0008     │
├───────────────────────┴─────────────┴────────────────┴─────────────┤
│ 💡 Switch to Claude Sonnet: +8.3% resolution rate (p=0.02)         │
│    LLM cost +$21/mo vs. escalation savings of $2,100/mo            │
│    Net impact: save $2,079/month                                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## What is Coii?

Most LLM teams eventually hit the same question: *"We have GPT-4o, Claude Sonnet, and Gemini — which one should we actually use in production?"*

Existing tools only solve part of the problem:

| Tool | What it does | What's missing |
|------|-------------|----------------|
| **Statsig** | A/B testing | Doesn't understand LLMs — no token cost, no ROI |
| **Langfuse** | LLM observability | No A/B testing, no business outcome tracking |
| **Promptfoo** | Offline model evals | No production traffic, no business outcomes |

Coii connects all three: **model routing + cost tracking + business outcomes** in a single server you run in 60 seconds.

---

## Features

- 🧪 **A/B test any models** — OpenAI, Anthropic, Google, DeepSeek, OpenRouter, or any OpenAI-compatible endpoint
- 💰 **Automatic cost tracking** — no extra code; built-in pricing for 30+ models, user-overridable
- 📊 **Statistical significance** — two-proportion z-test with Bonferroni correction for multiple challengers
- 🎯 **Business outcome attribution** — tie LLM calls to real conversions within a configurable time window
- 💡 **Plain-English recommendations** — net ROI in dollars, not just p-values
- 🗄️ **SQLite or Postgres** — SQLite for local dev, drop-in Postgres for production
- 🖥️ **React Dashboard** — built and embedded; no separate deploy needed
- 🐍 **3-line SDK integration** — `instrument`, `start`, `outcome`; that's the entire API

---

## Quick Start

```bash
pip install coii-server coii
coii serve
# → Dashboard  http://localhost:8080
# → API docs   http://localhost:8080/docs
```

No database setup needed — uses SQLite by default. For Postgres:

```bash
coii serve --database-url postgresql://localhost:5432/coii
```

### Step 1 — Create an experiment

Open `http://localhost:8080` → **New Experiment**.

- Set your **current model** (e.g. OpenAI / GPT-4o)
- Add **challengers** (e.g. Anthropic / Claude Sonnet 4.6, Google / Gemini 2.5 Flash)
- Set traffic split (e.g. 60 / 20 / 20)
- Name the outcomes you care about (e.g. `ticket_resolved`, `escalated_to_human`)

### Step 2 — Instrument your app

```python
from coii import Coii
import openai

coii = Coii(host="http://localhost:8080")
client = openai.OpenAI()
coii.instrument(client)                    # patches the SDK — tracks latency, tokens, cost

def handle_request(user_id: str, message: str) -> str:
    ctx = coii.start(user_id)              # creates trace, gets variant assignment
    response = client.chat.completions.create(
        model=ctx.model,                   # "gpt-4o" or "claude-sonnet-4-6" — set by experiment
        messages=[{"role": "user", "content": message}],
        temperature=ctx.config.get("temperature", 0.7),
    )
    return response.choices[0].message.content

def on_ticket_resolved(user_id: str):
    coii.outcome(user_id, "ticket_resolved")   # async, non-blocking, fire and forget
```

### Step 3 — Read the results

After enough traffic, the Dashboard shows a per-variant breakdown with statistical significance and a net-ROI recommendation. One click to switch.

---

## Self-host or use Coii Cloud

Coii is **free to self-host, forever.** The code is MIT and will stay that way.

If you'd rather not manage the infrastructure, **[Coii Cloud](https://coii.dev)** is a hosted version with:

- Zero setup — no Postgres, no server
- Team collaboration and role-based access
- Longer data retention
- Priority support

[**→ Start free on Coii Cloud**](https://coii.dev) — no credit card required.

---

## SDK Reference

### `Coii(host, api_key=None, default_model=None)`

```python
coii = Coii(host="http://localhost:8080")
coii = Coii(host="https://app.coii.dev", api_key="ck_...")   # Coii Cloud
```

### `coii.instrument(client)`

Patches an LLM SDK to auto-track every call. Supports:

- **OpenAI Python SDK** — also covers OpenRouter, DeepSeek, Together, and any OpenAI-compatible endpoint
- **Anthropic Python SDK**

```python
coii.instrument(openai_client)
coii.instrument(anthropic_client)
coii.instrument(openrouter_client)   # openai.OpenAI(base_url="https://openrouter.ai/api/v1")
```

### `ctx = coii.start(user_id)`

Fetches variant assignments and returns a `CoiiContext`:

| Attribute | Type | Description |
|-----------|------|-------------|
| `ctx.model` | `str` | Model string from the experiment — pass directly to your SDK |
| `ctx.provider` | `str` | Provider name (`"openai"`, `"anthropic"`, etc.) |
| `ctx.config` | `dict` | Per-variant config (temperature, max_tokens, etc.) |
| `ctx.prompt_version` | `str \| None` | Prompt version tag, if set on the variant |
| `ctx.variants` | `dict` | All assignments (for parallel experiments) |
| `ctx.trace_id` | `str` | Trace ID for this interaction |

### `coii.outcome(user_id, event, properties=None)`

Records a business outcome. Async and non-blocking.

```python
coii.outcome(user_id, "ticket_resolved")
coii.outcome(user_id, "purchase", {"amount_usd": 49.00})
ctx.outcome("ticket_resolved")              # shorthand when ctx is in scope
```

---

## Common Patterns

<details>
<summary><strong>Single-provider comparison</strong> (GPT-4o vs GPT-4o-mini)</summary>

```python
# Dashboard: Current=OpenAI/GPT-4o, Challenger=OpenAI/GPT-4o-mini
ctx = coii.start(user_id)
response = client.chat.completions.create(model=ctx.model, messages=[...])
```

</details>

<details>
<summary><strong>Cross-provider via OpenRouter</strong> (recommended for multi-provider)</summary>

```python
client = openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key="or_...")
coii.instrument(client)

# Dashboard: Current=OpenRouter/openai/gpt-4o
#         Challenger=OpenRouter/anthropic/claude-sonnet-4-6
ctx = coii.start(user_id)
response = client.chat.completions.create(model=ctx.model, messages=[...])
```

</details>

<details>
<summary><strong>Cross-provider with native SDKs</strong></summary>

```python
coii.instrument(openai_client)
coii.instrument(anthropic_client)

ctx = coii.start(user_id)
if ctx.provider == "openai":
    resp = openai_client.chat.completions.create(model=ctx.model, messages=[...])
elif ctx.provider == "anthropic":
    resp = anthropic_client.messages.create(model=ctx.model, messages=[...])
```

</details>

<details>
<summary><strong>Multiple parallel experiments</strong></summary>

```python
ctx = coii.start(user_id)
# ctx.model             → from the "model-selection" experiment
# ctx.variants[...]     → from any other running experiment

prompt_variant = ctx.variants.get("prompt-tone")
response = client.chat.completions.create(
    model=ctx.model,
    messages=[{
        "role": "system",
        "content": load_prompt(prompt_variant.prompt_version if prompt_variant else "v1")
    }, {"role": "user", "content": message}],
)
```

</details>

<details>
<summary><strong>Observation only</strong> (no experiment — just track cost and latency)</summary>

```python
coii = Coii(host="http://localhost:8080", default_model="gpt-4o")
ctx = coii.start(user_id)   # ctx.model == "gpt-4o"
# instrument still records cost and latency to build a baseline
```

</details>

---

## Supported Models

Built-in pricing for 30+ models. Override any price or add custom models in **Settings → Pricing**.

| Provider | Models |
|----------|--------|
| **OpenAI** | GPT-4.1, GPT-4.1 mini/nano, GPT-4o, GPT-4o mini, o3, o3-mini, o4-mini, GPT-4 Turbo |
| **Anthropic** | Claude Opus 4, Sonnet 4.6/4.5/3.7/3.5, Haiku 4.5/3.5 |
| **Google** | Gemini 2.5 Pro/Flash, 2.0 Flash, 1.5 Pro/Flash |
| **DeepSeek** | R1, V3, R1-0528 |
| **OpenRouter** | All of the above + free-tier Llama 3.3, Gemma 3, DeepSeek R1 |

---

## REST API

All endpoints are available at `http://localhost:8080/api/v1`. Interactive docs at `/docs`.

```
# Experiments
POST   /experiments                     Create
GET    /experiments                     List
GET    /experiments/{name}              Get
PATCH  /experiments/{name}              Update
POST   /experiments/{name}/start        Start
POST   /experiments/{name}/stop         Stop
POST   /experiments/{name}/switch       Switch to winning variant
GET    /experiments/{name}/results      Analysis results

# SDK endpoints (called by the Python SDK)
GET    /assignments?user_id=...         Get variant assignments
POST   /traces                          Create trace
PATCH  /traces/{id}/end                 End trace
POST   /spans                           Record LLM call
POST   /outcomes                        Record business outcome

# Pricing & Registry
GET    /pricing                         List all pricing
PUT    /pricing/{key}                   Upsert pricing
DELETE /pricing/{key}                   Delete user pricing
GET    /registry/providers              List providers
GET    /registry/models?provider=...    List models for a provider
```

---

## Project Structure

```
coii/
├── server/                             # FastAPI backend  →  pip install coii-server
│   └── coii_server/
│       ├── api/v1/
│       │   ├── experiments.py          # Experiment CRUD + lifecycle endpoints
│       │   ├── sdk.py                  # assignments / traces / spans / outcomes
│       │   ├── pricing.py              # Pricing management
│       │   └── registry.py            # Provider + model dropdown data
│       ├── activities/                 # Business logic (Ok/Err, never raises)
│       │   ├── experiments.py
│       │   ├── sdk.py                  # Assignment bucketing + cost computation
│       │   ├── analysis.py             # z-test, Bonferroni, ROI engine
│       │   └── pricing.py
│       ├── models/orm.py               # SQLAlchemy models
│       ├── db/                         # Init + built-in pricing seed
│       ├── utils/                      # Ok/Err result type, ULID IDs
│       ├── cli.py                      # `coii serve` entry point
│       └── app.py                      # FastAPI app factory
│
├── sdk/                                # Python SDK  →  pip install coii
│   └── coii/
│       ├── client.py                   # Coii: instrument / start / outcome
│       └── context.py                  # CoiiContext: model / provider / config
│
├── frontend/                           # React dashboard (Vite + Tailwind)
│   └── src/
│       ├── pages/
│       │   ├── ExperimentsPage.tsx
│       │   ├── ExperimentDetailPage.tsx    # Results table + recommendation
│       │   ├── CreateExperimentPage.tsx    # Variant form with provider dropdowns
│       │   └── PricingPage.tsx
│       └── api/client.ts               # Typed fetch client
│
└── tests/
    └── e2e/test_full_flow.py           # 37 end-to-end integration tests
```

---

## Contributing

Contributions are welcome — bug fixes, new model support, documentation improvements, and feature work.

### Getting started

```bash
git clone https://github.com/coii-dev/coii.git
cd coii

# Backend
cd server
python -m venv .venv && source .venv/bin/activate
pip install -e .
PYTHONPATH=. coii serve --reload      # http://localhost:8080

# Frontend (separate terminal)
cd frontend
npm install
npm run dev                            # http://localhost:5173 — proxies API to :8080
```

### Running the tests

```bash
cd server
pip install pytest pytest-asyncio httpx
PYTHONPATH=. pytest ../tests/e2e/test_full_flow.py -v
# → 37 passed  (in-memory SQLite, no running server needed)
```

### Before opening a PR

- Tests pass (`pytest -v`)
- New behaviour has a test
- For larger changes, open an issue first to align on direction

### Ways to contribute

- **🐛 Bug reports** — [open an issue](https://github.com/coii-dev/coii/issues/new?template=bug_report.md)
- **✨ Feature requests** — [open a discussion](https://github.com/coii-dev/coii/discussions)
- **📖 Docs** — typos, unclear wording, missing examples all count
- **🔌 New provider / model support** — add entries to `registry.py` and `seed.py`
- **🌍 Integrations** — TypeScript SDK, LangChain wrapper, async SDK support

---

## Architecture

### Layered backend

```
HTTP Request
    ↓
Controller  (FastAPI router)    extract params, map Ok/Err → HTTP status
    ↓
Activity    (business logic)    returns Ok(value) | Err(code, msg), never raises
    ↓
SQLAlchemy  (async)             SQLite in dev · PostgreSQL in production
```

### How cost tracking works

`coii.instrument(client)` monkey-patches the LLM SDK. After each call it sends a span to the server with model name, latency, and token counts. **No credentials or prompt content are ever sent to Coii.**

The server computes cost server-side:

```
span.model  +  variant.provider   →   pricing_key  (e.g. "openai/gpt-4o")
                                  →   model_pricing table
                                  →   cost_usd = input_tokens/1M × $in
                                               + output_tokens/1M × $out
```

### Data model

Four independent tables, joined at analysis time via `user_id + time window`:

```
experiments   exposures      traces         outcomes
────────────  ────────────   ────────────   ────────────
config        user_id ─────► user_id        user_id
variants      variant        session_id     event_name
status        experiment_id  │              properties
                             ▼
                           spans
                           ──────────────────────────
                           trace_id  ·  type  ·  model
                           tokens    ·  cost   ·  latency
```

No hard foreign key between `traces` and `exposures` — a user can be enrolled in multiple experiments simultaneously. Analysis joins dynamically, same pattern as Statsig.

### Statistical engine

- **Two-proportion z-test** for binary outcome metrics
- **Bonferroni correction** for multiple simultaneous challengers
- Configurable attribution window (default 7 days)
- Net ROI: `(conversion lift × value per conversion) − (LLM cost delta)`

---

## Out of scope (Phase 1)

| Feature | Rationale | Alternatives |
|---------|-----------|--------------|
| Request / response content logging | Observability scope | Langfuse, Helicone |
| LLM-as-judge evaluation | Business outcome is the signal | DeepEval, RAGAS |
| Red-teaming / safety testing | Different problem domain | Promptfoo, Garak |
| Multi-provider API proxy | Not Coii's responsibility | OpenRouter, LiteLLM |
| Docker Compose setup | Phase 2 | — |
| TypeScript SDK | Phase 2 | — |

---

## License

[MIT](LICENSE) — free to use, modify, and self-host.

Coii is open source and will stay that way. If you'd rather skip the infrastructure, [Coii Cloud](https://coii.dev) offers a hosted version with team features and priority support.
