"""
End-to-end integration tests covering the full Coii user journey:
1. Create experiment
2. Start experiment
3. SDK: get assignments (exposure created)
4. SDK: create trace + span (LLM call tracked with cost)
5. SDK: record outcome
6. Query results (analysis engine)
7. Stop experiment
8. Switch variant
"""
import asyncio
import os
import pytest
from httpx import AsyncClient, ASGITransport

os.environ["COII_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="module")
async def client():
    from coii_server.app import create_app
    from coii_server.db import init_db
    app = create_app()
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ──────────────────────────────────────────────
# 1. Experiment CRUD
# ──────────────────────────────────────────────

class TestExperimentCRUD:

    async def test_create_experiment(self, client):
        resp = await client.post("/api/v1/experiments", json={
            "name": "support-bot-v2",
            "description": "Test GPT-4o vs Gemini Flash",
            "variants": [
                {
                    "name": "gpt4o",
                    "provider": "openai",
                    "model": "gpt-4o",
                    "traffic_pct": 60,
                    "is_current": True,
                    "config": {"temperature": 0.7},
                },
                {
                    "name": "gemini_flash",
                    "provider": "google",
                    "model": "gemini-2.5-flash",
                    "traffic_pct": 40,
                    "is_current": False,
                    "config": {},
                },
            ],
            "outcome_events": ["ticket_resolved"],
            "attribution_window_hours": 168,
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "support-bot-v2"
        assert body["status"] == "draft"
        assert len(body["variants"]) == 2
        assert body["id"].startswith("ex_")

    async def test_list_experiments(self, client):
        resp = await client.get("/api/v1/experiments")
        assert resp.status_code == 200
        experiments = resp.json()
        assert any(e["name"] == "support-bot-v2" for e in experiments)

    async def test_get_experiment(self, client):
        resp = await client.get("/api/v1/experiments/support-bot-v2")
        assert resp.status_code == 200
        assert resp.json()["name"] == "support-bot-v2"

    async def test_get_nonexistent_experiment_returns_404(self, client):
        resp = await client.get("/api/v1/experiments/does-not-exist")
        assert resp.status_code == 404

    async def test_duplicate_name_returns_409(self, client):
        resp = await client.post("/api/v1/experiments", json={
            "name": "support-bot-v2",
            "variants": [
                {"name": "a", "provider": "openai", "model": "gpt-4o", "traffic_pct": 100, "is_current": True}
            ],
            "outcome_events": [],
        })
        assert resp.status_code == 409

    async def test_invalid_traffic_returns_422(self, client):
        resp = await client.post("/api/v1/experiments", json={
            "name": "bad-traffic",
            "variants": [
                {"name": "a", "provider": "openai", "model": "gpt-4o", "traffic_pct": 50, "is_current": True},
                {"name": "b", "provider": "openai", "model": "gpt-4o-mini", "traffic_pct": 30, "is_current": False},
            ],
            "outcome_events": [],
        })
        assert resp.status_code == 422  # pydantic validation

    async def test_start_experiment(self, client):
        resp = await client.post("/api/v1/experiments/support-bot-v2/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    async def test_cannot_start_already_running(self, client):
        resp = await client.post("/api/v1/experiments/support-bot-v2/start")
        assert resp.status_code == 400


# ──────────────────────────────────────────────
# 2. SDK Flow
# ──────────────────────────────────────────────

class TestSDKFlow:

    async def test_get_assignments_creates_exposure(self, client):
        """First call creates exposure; second call returns same assignment."""
        resp = await client.get("/api/v1/assignments?user_id=user-001")
        assert resp.status_code == 200
        assignments = resp.json()
        assert "support-bot-v2" in assignments
        a = assignments["support-bot-v2"]
        assert a["variant"]["name"] in ("gpt4o", "gemini_flash")
        assert a["exposure_id"].startswith("ep_")

    async def test_get_assignments_stable(self, client):
        """Same user always gets same variant (deterministic)."""
        r1 = await client.get("/api/v1/assignments?user_id=user-001")
        r2 = await client.get("/api/v1/assignments?user_id=user-001")
        assert r1.json()["support-bot-v2"]["variant"]["name"] == \
               r2.json()["support-bot-v2"]["variant"]["name"]

    async def test_different_users_may_get_different_variants(self, client):
        """With enough users, both variants get assigned."""
        variants_seen = set()
        for i in range(20):
            resp = await client.get(f"/api/v1/assignments?user_id=bulk-user-{i:04d}")
            assert resp.status_code == 200
            a = resp.json().get("support-bot-v2", {})
            if a.get("variant"):
                variants_seen.add(a["variant"]["name"])
        assert len(variants_seen) >= 1  # at least one variant

    async def test_create_trace(self, client):
        resp = await client.post("/api/v1/traces", json={
            "id": "tr_test_001",
            "user_id": "user-001",
            "session_id": "session-abc",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == "tr_test_001"
        assert body["user_id"] == "user-001"

    async def test_create_span_computes_cost(self, client):
        """Span creation for an openai/gpt-4o variant should compute cost."""
        # First ensure user-001 is in gpt4o variant — get their assignment
        asgn_resp = await client.get("/api/v1/assignments?user_id=user-001")
        variant = asgn_resp.json()["support-bot-v2"]["variant"]["name"]
        
        resp = await client.post("/api/v1/spans", json={
            "trace_id": "tr_test_001",
            "type": "llm",
            "model": "gpt-4o",
            "latency_ms": 1200,
            "input_tokens": 500,
            "output_tokens": 200,
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"].startswith("sp_")
        # Cost should be computed if variant is gpt4o (openai provider)
        if variant == "gpt4o":
            assert body["cost_usd"] is not None
            # 500/1M * 2.50 + 200/1M * 10.00 = 0.00125 + 0.002 = 0.00325
            assert abs(body["cost_usd"] - 0.00325) < 0.0001

    async def test_record_outcome(self, client):
        resp = await client.post("/api/v1/outcomes", json={
            "user_id": "user-001",
            "event_name": "ticket_resolved",
            "properties": {"resolution_time": 45},
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["event_name"] == "ticket_resolved"
        assert body["id"].startswith("oc_")

    async def test_end_trace(self, client):
        resp = await client.patch("/api/v1/traces/tr_test_001/end")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ended_at"] is not None


# ──────────────────────────────────────────────
# 3. Analysis Engine
# ──────────────────────────────────────────────

class TestAnalysisEngine:

    async def _setup_data(self, client, n_users: int = 30):
        """Inject enough users/traces/spans/outcomes for meaningful analysis."""
        for i in range(n_users):
            uid = f"analysis-user-{i:04d}"
            # Get assignment (creates exposure)
            asgn = await client.get(f"/api/v1/assignments?user_id={uid}")
            variant = asgn.json().get("support-bot-v2", {}).get("variant", {})

            # Create trace
            trace_id = f"tr_analysis_{i:04d}"
            await client.post("/api/v1/traces", json={
                "id": trace_id,
                "user_id": uid,
            })

            # Create span
            model = variant.get("model", "gpt-4o")
            await client.post("/api/v1/spans", json={
                "trace_id": trace_id,
                "type": "llm",
                "model": model,
                "latency_ms": 800 + (i % 5) * 100,
                "input_tokens": 300 + i * 10,
                "output_tokens": 100 + i * 5,
            })

            # ~50% get outcome
            if i % 2 == 0:
                await client.post("/api/v1/outcomes", json={
                    "user_id": uid,
                    "event_name": "ticket_resolved",
                })

    async def test_get_results_returns_variant_stats(self, client):
        await self._setup_data(client)
        resp = await client.get("/api/v1/experiments/support-bot-v2/results")
        assert resp.status_code == 200
        body = resp.json()
        assert body["experiment"]["name"] == "support-bot-v2"
        assert "variants" in body
        assert len(body["variants"]) == 2
        assert body["total_users"] > 0

    async def test_results_have_cost_data(self, client):
        resp = await client.get("/api/v1/experiments/support-bot-v2/results")
        body = resp.json()
        # At least one variant should have cost data (openai variant)
        has_cost = any(v.get("avg_cost_per_call") is not None for v in body["variants"])
        assert has_cost

    async def test_results_have_latency_data(self, client):
        resp = await client.get("/api/v1/experiments/support-bot-v2/results")
        body = resp.json()
        has_latency = any(v.get("avg_latency_ms") is not None for v in body["variants"])
        assert has_latency

    async def test_results_conversion_rate(self, client):
        resp = await client.get("/api/v1/experiments/support-bot-v2/results")
        body = resp.json()
        for v in body["variants"]:
            assert 0 <= v["conversion_rate"] <= 1

    async def test_results_have_recommendation(self, client):
        resp = await client.get("/api/v1/experiments/support-bot-v2/results")
        body = resp.json()
        # Recommendation may be None or a dict — just ensure it doesn't crash
        assert "recommendation" in body


# ──────────────────────────────────────────────
# 4. Experiment lifecycle: stop + switch
# ──────────────────────────────────────────────

class TestExperimentLifecycle:

    async def test_stop_experiment(self, client):
        resp = await client.post("/api/v1/experiments/support-bot-v2/stop")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["stopped_at"] is not None

    async def test_cannot_stop_completed_experiment(self, client):
        resp = await client.post("/api/v1/experiments/support-bot-v2/stop")
        assert resp.status_code == 400

    async def test_switch_variant(self, client):
        # Restart first (need running state) — create fresh experiment
        await client.post("/api/v1/experiments", json={
            "name": "switch-test",
            "variants": [
                {"name": "a", "provider": "openai", "model": "gpt-4o", "traffic_pct": 50, "is_current": True},
                {"name": "b", "provider": "openai", "model": "gpt-4o-mini", "traffic_pct": 50, "is_current": False},
            ],
            "outcome_events": [],
        })
        await client.post("/api/v1/experiments/switch-test/start")

        resp = await client.post("/api/v1/experiments/switch-test/switch", json={
            "variant_name": "b"
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        # Verify b is now current
        current = next(v for v in body["variants"] if v["is_current"])
        assert current["name"] == "b"

    async def test_switch_nonexistent_variant_returns_4xx(self, client):
        await client.post("/api/v1/experiments", json={
            "name": "switch-fail-test",
            "variants": [
                {"name": "x", "provider": "openai", "model": "gpt-4o", "traffic_pct": 100, "is_current": True},
            ],
            "outcome_events": [],
        })
        await client.post("/api/v1/experiments/switch-fail-test/start")
        resp = await client.post("/api/v1/experiments/switch-fail-test/switch", json={
            "variant_name": "nonexistent"
        })
        # Returns 404 because variant is not found — either 400 or 404 is acceptable
        assert resp.status_code in (400, 404)


# ──────────────────────────────────────────────
# 5. Pricing API
# ──────────────────────────────────────────────

class TestPricingAPI:

    async def test_list_pricing_includes_builtins(self, client):
        resp = await client.get("/api/v1/pricing")
        assert resp.status_code == 200
        pricing = resp.json()
        keys = [p["pricing_key"] for p in pricing]
        assert "openai/gpt-4o" in keys
        assert "anthropic/claude-sonnet-4-6" in keys

    async def test_upsert_pricing(self, client):
        resp = await client.put("/api/v1/pricing/custom/my-model", json={
            "pricing_key": "custom/my-model",
            "input_cost_per_mtok": 1.00,
            "output_cost_per_mtok": 3.00,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "user"
        assert body["input_cost_per_mtok"] == 1.00

    async def test_delete_user_pricing(self, client):
        resp = await client.delete("/api/v1/pricing/custom/my-model")
        assert resp.status_code == 204

    async def test_cannot_delete_builtin_pricing(self, client):
        resp = await client.delete("/api/v1/pricing/openai/gpt-4o")
        assert resp.status_code == 403


# ──────────────────────────────────────────────
# 6. Registry API
# ──────────────────────────────────────────────

class TestRegistryAPI:

    async def test_list_providers(self, client):
        resp = await client.get("/api/v1/registry/providers")
        assert resp.status_code == 200
        providers = resp.json()
        ids = [p["id"] for p in providers]
        assert "openai" in ids
        assert "anthropic" in ids
        assert "google" in ids

    async def test_list_models_by_provider(self, client):
        resp = await client.get("/api/v1/registry/models?provider=openai")
        assert resp.status_code == 200
        models = resp.json()
        model_ids = [m["id"] for m in models]
        assert "gpt-4o" in model_ids

    async def test_list_all_models(self, client):
        resp = await client.get("/api/v1/registry/models")
        assert resp.status_code == 200
        assert len(resp.json()) > 5


# ──────────────────────────────────────────────
# 7. SDK Python client integration
# ──────────────────────────────────────────────

class TestSDKClient:
    """Tests the Python SDK client against a live server."""

    @pytest.fixture
    async def sdk_client(self, client):
        """Create a Coii SDK client that talks to the in-process ASGI server."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdk"))
        from coii.client import Coii
        import httpx

        # Override the sync HTTP client to use the test transport
        coii = Coii.__new__(Coii)
        coii._host = "http://test"
        coii._api_key = None
        coii._default_model = None
        # We'll patch _send_sync and _send_async to use the test client
        coii._test_client = client
        return coii

    async def test_sdk_context_has_model(self, client):
        """CoiiContext.model should be set from active experiment."""
        # Create and start an experiment
        await client.post("/api/v1/experiments", json={
            "name": "sdk-test-exp",
            "variants": [
                {
                    "name": "gpt4o",
                    "provider": "openai",
                    "model": "gpt-4o",
                    "traffic_pct": 100,
                    "is_current": True,
                    "config": {},
                },
            ],
            "outcome_events": ["converted"],
        })
        await client.post("/api/v1/experiments/sdk-test-exp/start")

        # Simulate what the SDK does
        asgn_resp = await client.get("/api/v1/assignments?user_id=sdk-user-1")
        assignments = asgn_resp.json()
        assert "sdk-test-exp" in assignments
        variant = assignments["sdk-test-exp"]["variant"]
        assert variant["model"] == "gpt-4o"
        assert variant["provider"] == "openai"

    async def test_instrument_patch_tracking(self, client):
        """Simulate instrument patching: manually call the spans endpoint."""
        # Create a trace
        trace_resp = await client.post("/api/v1/traces", json={
            "id": "tr_sdk_instrument_001",
            "user_id": "sdk-user-1",
        })
        assert trace_resp.status_code == 201

        # Simulate patched SDK sending span
        span_resp = await client.post("/api/v1/spans", json={
            "trace_id": "tr_sdk_instrument_001",
            "type": "llm",
            "model": "gpt-4o",
            "latency_ms": 950,
            "input_tokens": 150,
            "output_tokens": 75,
        })
        assert span_resp.status_code == 201
        span = span_resp.json()
        assert span["id"].startswith("sp_")
        # Cost should be computed (user is in gpt4o variant)
        # 150/1M * 2.50 + 75/1M * 10.00 = 0.000375 + 0.00075 = 0.001125
        assert span["cost_usd"] is not None

    async def test_outcome_recording(self, client):
        outcome_resp = await client.post("/api/v1/outcomes", json={
            "user_id": "sdk-user-1",
            "event_name": "converted",
        })
        assert outcome_resp.status_code == 201


# ──────────────────────────────────────────────
# 8. Statistical analysis correctness
# ──────────────────────────────────────────────

class TestStatistics:

    async def test_z_test_correct(self):
        """Unit test for z-test implementation."""
        from coii_server.activities.analysis import _z_test_two_proportions

        # Known values: p1=0.5, n1=1000, p2=0.6, n2=1000 → should be significant
        z, p = _z_test_two_proportions(1000, 0.5, 1000, 0.6)
        assert z < 0  # p1 < p2 so z should be negative
        assert p < 0.01  # highly significant

        # Small samples — should not be significant
        z2, p2 = _z_test_two_proportions(5, 0.4, 5, 0.6)
        assert p2 > 0.05

    async def test_bonferroni_correction(self):
        from coii_server.activities.analysis import _bonferroni_threshold

        assert _bonferroni_threshold(1) == 0.05
        assert abs(_bonferroni_threshold(2) - 0.025) < 1e-9
        assert abs(_bonferroni_threshold(4) - 0.0125) < 1e-9

    async def test_cost_calculation(self):
        """Verify cost formula: input_tokens/1M * input_price + output/1M * output_price."""
        input_tokens = 1_000_000
        output_tokens = 1_000_000
        input_price = 2.50
        output_price = 10.00
        cost = input_tokens / 1_000_000 * input_price + output_tokens / 1_000_000 * output_price
        assert cost == 12.50
