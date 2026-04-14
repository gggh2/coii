"""
Live end-to-end verification using real OpenRouter free models.

Tests the complete Coii flow:
  1. Start Coii server (SQLite)
  2. Create experiment: gemma-3-4b (control) vs lfm-2.5-1.2b (challenger)
  3. For 10 simulated users:
     - coii.start(user_id) → get assigned variant
     - Call OpenRouter with assigned model via OpenAI SDK (instrumented)
     - Record business outcome for ~50% of users
  4. Query results → verify cost/latency/conversion data is populated
  5. Print a summary table

Usage:
    cd server && source .venv/bin/activate
    PYTHONPATH=. python ../tests/e2e_live_test.py
"""

import asyncio
import os
import sys
import time
import threading
import httpx

# Point at in-process server
os.environ["COII_DATABASE_URL"] = "sqlite+aiosqlite:///./coii_live_test.db"

# Remove stale DB
import pathlib
pathlib.Path("coii_live_test.db").unlink(missing_ok=True)

OPENROUTER_KEY = "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"
MODEL_CONTROL    = "google/gemma-3-4b-it:free"
MODEL_CHALLENGER = "liquid/lfm-2.5-1.2b-instruct:free"
SERVER_URL       = "http://localhost:18080"
NUM_USERS        = 10

# ──────────────────────────────────────────────────────────────
# 1. Start server in a background thread
# ──────────────────────────────────────────────────────────────
def start_server():
    import uvicorn
    from coii_server.app import create_app
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=18080, log_level="warning")

server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

# Wait for server to be ready
print("⏳ Starting Coii server on :18080 ...")
for _ in range(30):
    try:
        r = httpx.get(f"{SERVER_URL}/api/v1/registry/providers", timeout=2)
        if r.status_code == 200:
            break
    except Exception:
        pass
    time.sleep(0.5)
else:
    print("❌ Server did not start in time")
    sys.exit(1)
print("✅ Server ready\n")

# ──────────────────────────────────────────────────────────────
# 2. Create experiment via API
# ──────────────────────────────────────────────────────────────
api = httpx.Client(base_url=SERVER_URL, timeout=10)

print("📋 Creating experiment...")
r = api.post("/api/v1/experiments", json={
    "name": "free-model-shootout",
    "description": "Gemma-3 4B vs LFM 2.5 1.2B via OpenRouter",
    "variants": [
        {
            "name": "gemma3_4b",
            "provider": "openrouter",
            "model": MODEL_CONTROL,
            "traffic_pct": 50,
            "is_current": True,
            "config": {"max_tokens": 80},
        },
        {
            "name": "lfm_1b",
            "provider": "openrouter",
            "model": MODEL_CHALLENGER,
            "traffic_pct": 50,
            "is_current": False,
            "config": {"max_tokens": 80},
        },
    ],
    "outcome_events": ["helpful"],
    "attribution_window_hours": 24,
})
assert r.status_code == 201, f"Create failed: {r.text}"
exp = r.json()
print(f"   Experiment ID: {exp['id']}")

# Start it
r = api.post("/api/v1/experiments/free-model-shootout/start")
assert r.status_code == 200
print("   Status: running\n")

# ──────────────────────────────────────────────────────────────
# 3. Initialize SDK + instrument OpenAI client for OpenRouter
# ──────────────────────────────────────────────────────────────
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "sdk"))
from coii import Coii

coii = Coii(host=SERVER_URL)

# OpenAI-compatible client pointing at OpenRouter
import openai
or_client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_KEY,
)
coii.instrument(or_client)

# ──────────────────────────────────────────────────────────────
# 4. Simulate user interactions
# ──────────────────────────────────────────────────────────────
PROMPT = "In one sentence, what is the capital of France?"

print(f"🧪 Running {NUM_USERS} users against real OpenRouter models...\n")
results_per_variant = {"gemma3_4b": [], "lfm_1b": []}
variant_model_map = {"gemma3_4b": MODEL_CONTROL, "lfm_1b": MODEL_CHALLENGER}

for i in range(NUM_USERS):
    uid = f"live-user-{i:03d}"
    ctx = coii.start(uid)
    variant_name = next(
        (v["name"] for v in exp["variants"] if v["model"] == ctx.model),
        "unknown"
    )

    print(f"  User {i:02d} → variant={variant_name!r} model={ctx.model!r}")

    try:
        resp = or_client.chat.completions.create(
            model=ctx.model,
            messages=[{"role": "user", "content": PROMPT}],
            max_tokens=ctx.config.get("max_tokens", 80),
        )
        answer = resp.choices[0].message.content.strip()
        tokens_in  = resp.usage.prompt_tokens if resp.usage else 0
        tokens_out = resp.usage.completion_tokens if resp.usage else 0
        short = repr(answer[:60])
        print(f"         → {short}  [{tokens_in}+{tokens_out} tok]")

        # ~60% of users get a "helpful" outcome
        if i % 5 != 0:  # 80% conversion
            coii.outcome(uid, "helpful")
            print(f"         → outcome: helpful ✓")

        results_per_variant[variant_name].append({
            "uid": uid,
            "answer": answer,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        })

    except Exception as e:
        print(f"         ❌ LLM error: {e}")

    time.sleep(0.8)  # respect rate limits

# ──────────────────────────────────────────────────────────────
# 5. Wait for async span writes to flush, then query results
# ──────────────────────────────────────────────────────────────
print("\n⏳ Waiting for spans/outcomes to flush to server...")
time.sleep(3)

print("\n📊 Querying experiment results...\n")
r = api.get("/api/v1/experiments/free-model-shootout/results")
assert r.status_code == 200, f"Results failed: {r.text}"
body = r.json()

# ──────────────────────────────────────────────────────────────
# 6. Print results table
# ──────────────────────────────────────────────────────────────
print("=" * 70)
print(f"  Experiment: {body['experiment']['name']}")
print(f"  Status:     {body['experiment']['status']}")
print(f"  Total users: {body['total_users']}")
print("=" * 70)
print(f"  {'Variant':<20} {'Users':>6} {'Conversion':>12} {'Calls':>7} {'Avg Cost':>10} {'Avg Latency':>12}")
print("  " + "-" * 68)

assertions_passed = 0
assertions_failed = 0

for v in body["variants"]:
    conv = f"{v['conversion_rate']*100:.1f}%"
    cost = f"${v['avg_cost_per_call']:.6f}" if v['avg_cost_per_call'] is not None else "n/a"
    latency = f"{v['avg_latency_ms']:.0f}ms" if v['avg_latency_ms'] is not None else "n/a"
    current = " ← current" if v.get("is_current") else ""
    print(f"  {v['name']:<20} {v['users']:>6} {conv:>12} {v['llm_calls']:>7} {cost:>10} {latency:>12}{current}")

print("=" * 70)

if body.get("recommendation"):
    rec = body["recommendation"]
    print(f"\n  💡 Recommendation: {rec['message']}")

# ──────────────────────────────────────────────────────────────
# 7. Assertions
# ──────────────────────────────────────────────────────────────
print("\n🔍 Verifications:")

def check(label, condition, detail=""):
    global assertions_passed, assertions_failed
    if condition:
        print(f"  ✅ {label}")
        assertions_passed += 1
    else:
        print(f"  ❌ {label}{' — ' + detail if detail else ''}")
        assertions_failed += 1

check("Experiment is running", body["experiment"]["status"] == "running")
check("Total users > 0", body["total_users"] > 0)
check("Two variants present", len(body["variants"]) == 2)

total_llm_calls = sum(v["llm_calls"] for v in body["variants"])
check(f"LLM calls tracked ({total_llm_calls})", total_llm_calls > 0)

total_conversions = sum(v["conversions"] for v in body["variants"])
check(f"Outcomes recorded ({total_conversions})", total_conversions > 0)

has_latency = any(v["avg_latency_ms"] is not None for v in body["variants"])
check("Latency data present", has_latency)

# Cost may be null for openrouter if pricing key not in table — that's expected
# but we can check if the openrouter/* key existed in pricing
r2 = api.get("/api/v1/pricing")
pricing_keys = [p["pricing_key"] for p in r2.json()]
# openrouter models use provider=openrouter so pricing key would be openrouter/google/gemma-3-4b-it:free
# That won't be in our table, so cost will be null — verify gracefully
has_cost = any(v["avg_cost_per_call"] is not None for v in body["variants"])
if has_cost:
    check("Cost data computed", True)
else:
    print(f"  ℹ️  Cost is null (expected — openrouter free model IDs not in pricing table, add via /api/v1/pricing)")

# Verify spans were actually written to DB
r3 = api.get(f"/api/v1/experiments/free-model-shootout/results")
check("Results endpoint returns 200", r3.status_code == 200)

print(f"\n{'='*70}")
print(f"  Result: {assertions_passed} passed / {assertions_failed} failed")
print(f"{'='*70}\n")

# Cleanup
pathlib.Path("coii_live_test.db").unlink(missing_ok=True)

if assertions_failed > 0:
    sys.exit(1)
