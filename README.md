# Coii

Open-source LLM A/B testing with real business outcomes. Run experiments across models, track cost and conversion in production, and get a plain-English recommendation.

```
┌───────────────────────┬─────────────┬────────────────┬─────────────┐
│                       │ GPT-4o      │ Claude Sonnet  │ Gemini Flash│
│                       │ (current)   │ (challenger)   │ (challenger)│
├───────────────────────┼─────────────┼────────────────┼─────────────┤
│ Users                 │ 1,441       │ 481            │ 480         │
│ Ticket resolution     │ 72%         │ 78% ✓ +8.3%   │ 65%         │
│ Avg cost / request    │ $0.0034     │ $0.0041        │ $0.0008     │
├───────────────────────┴─────────────┴────────────────┴─────────────┤
│ Switch to Claude Sonnet: +8.3% resolution rate (p=0.02)            │
│ Net impact: save $2,079/month                                       │
└─────────────────────────────────────────────────────────────────────┘
```

## Quick Start

**Server**

```bash
cd server
uv run --with hatchling pip install -e .
uv run coii serve
# → Dashboard  http://localhost:8080
```

**SDK**

```bash
cd sdk
uv pip install -e .
```

**Frontend** (optional, dashboard is embedded in the server)

```bash
cd frontend
npm install && npm run dev   # http://localhost:5173 — proxies API to :8080
```

## Usage

```python
from coii import Coii
import openai

coii = Coii(host="http://localhost:8080")
client = openai.OpenAI()
coii.instrument(client)          # patches SDK — tracks latency, tokens, cost

def handle(user_id: str, message: str) -> str:
    ctx = coii.start(user_id)    # gets variant assignment
    resp = client.chat.completions.create(
        model=ctx.model,         # set by experiment; falls back to default_model
        messages=[{"role": "user", "content": message}],
    )
    return resp.choices[0].message.content

def on_resolved(user_id: str):
    coii.outcome(user_id, "ticket_resolved")   # ties outcome to LLM call
```

1. Open `http://localhost:8080` → **New Experiment**
2. Set current model + challengers + traffic split + outcome names
3. After enough traffic, the dashboard shows per-variant stats and a net-ROI recommendation

## License

[MIT](LICENSE)
