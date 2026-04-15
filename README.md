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

## Getting Started

### 1. Install

```bash
# Server
cd server
uv pip install -e .
uv run coii serve
# → Dashboard  http://localhost:8080
# → API docs   http://localhost:8080/docs
```

```bash
# SDK (separate terminal, in your app's virtualenv)
pip install coii-sdk
# or for local development: cd sdk && uv pip install -e .
```

### 2. Set up an experiment in the dashboard

1. Open `http://localhost:8080` → **New Experiment**
2. Fill in:
   - **Current model** — your production model (e.g. `openai / gpt-4o`, traffic 60%)
   - **Challengers** — models to test (e.g. `anthropic / claude-sonnet-4-6`, 20%; `google / gemini-2.5-flash`, 20%)
   - **Outcome events** — the business signals you care about (e.g. `ticket_resolved`, `purchase`)
3. Click **Start** — the experiment is now live and assigning users to variants

### 3. Instrument your code

```python
from coii import Coii
import openai

coii = Coii(host="http://localhost:8080")
client = openai.OpenAI()
coii.instrument(client)          # auto-tracks latency, tokens, cost

def handle(user_id: str, message: str) -> str:
    ctx = coii.start(user_id)    # assigns user to a variant
    resp = client.chat.completions.create(
        model=ctx.model,         # the assigned model — "gpt-4o", "claude-sonnet-4-6", etc.
        messages=[{"role": "user", "content": message}],
    )
    return resp.choices[0].message.content

def on_ticket_resolved(user_id: str):
    coii.outcome(user_id, "ticket_resolved")   # ties the outcome back to the variant
```

### 4. Read the results

Once you have enough traffic, open the experiment detail page in the dashboard. It shows per-variant conversion rates, cost, latency, statistical significance, and a plain-English recommendation with net ROI in dollars.

---

### Frontend dev server (optional)

The dashboard is embedded in the server binary. If you want to iterate on the frontend:

```bash
cd frontend
npm install && npm run dev   # http://localhost:5173 — proxies API to :8080
```

## License

[MIT](LICENSE)
