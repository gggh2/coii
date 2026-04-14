"""Analysis engine: statistical significance + cost economics."""
import math
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from coii_server.models.orm import Experiment, Exposure, Trace, Span, Outcome
from coii_server.utils import Ok, Err, Result


def _z_test_two_proportions(
    n1: int, p1: float, n2: int, p2: float
) -> tuple[float, float]:
    """Two-proportion z-test. Returns (z_score, p_value)."""
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p1 - p2) / se

    # Approximate p-value from standard normal (two-tailed)
    # Using Abramowitz & Stegun approximation
    abs_z = abs(z)
    t = 1 / (1 + 0.2316419 * abs_z)
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    p_one_tail = math.exp(-0.5 * abs_z ** 2) / math.sqrt(2 * math.pi) * poly
    p_value = min(2 * p_one_tail, 1.0)
    return z, p_value


def _bonferroni_threshold(num_challengers: int, alpha: float = 0.05) -> float:
    return alpha / max(num_challengers, 1)


class AnalysisActivity:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_results(self, experiment_name: str) -> Result:
        exp = await self.db.scalar(
            select(Experiment).where(Experiment.name == experiment_name)
        )
        if not exp:
            return Err("NOT_FOUND", f"Experiment '{experiment_name}' not found")

        variants = exp.variants
        attribution_hours = exp.attribution_window_hours
        outcome_events = exp.outcome_events

        # Per-variant stats
        variant_stats = {}
        for v in variants:
            stats = await self._compute_variant_stats(
                exp, v["name"], attribution_hours, outcome_events
            )
            variant_stats[v["name"]] = {**v, **stats}

        # Statistical significance (compare each challenger to current)
        current_v = next((v for v in variants if v.get("is_current")), variants[0] if variants else None)
        challengers = [v for v in variants if not v.get("is_current")]
        num_challengers = len(challengers)
        threshold = _bonferroni_threshold(num_challengers)

        for v_name, stats in variant_stats.items():
            if v_name == (current_v["name"] if current_v else None):
                stats["is_current"] = True
                stats["significance"] = None
                continue

            if current_v and outcome_events:
                curr_stats = variant_stats.get(current_v["name"], {})
                curr_n = curr_stats.get("users", 0)
                curr_conv = curr_stats.get("conversion_rate", 0.0)
                chal_n = stats.get("users", 0)
                chal_conv = stats.get("conversion_rate", 0.0)

                if curr_n > 0 and chal_n > 0:
                    z, p_val = _z_test_two_proportions(curr_n, curr_conv, chal_n, chal_conv)
                    stats["z_score"] = round(z, 4)
                    stats["p_value"] = round(p_val, 4)
                    stats["is_significant"] = p_val < threshold
                    stats["significance_threshold"] = threshold
                else:
                    stats["z_score"] = None
                    stats["p_value"] = None
                    stats["is_significant"] = False

        # Recommendation
        recommendation = self._generate_recommendation(
            variant_stats, current_v["name"] if current_v else None, outcome_events
        )

        return Ok(
            {
                "experiment": {
                    "public_id": exp.public_id,
                    "name": exp.name,
                    "status": exp.status,
                    "attribution_window_hours": attribution_hours,
                    "outcome_events": outcome_events,
                    "started_at": exp.started_at.isoformat() if exp.started_at else None,
                    "stopped_at": exp.stopped_at.isoformat() if exp.stopped_at else None,
                },
                "variants": list(variant_stats.values()),
                "recommendation": recommendation,
                "total_users": sum(s.get("users", 0) for s in variant_stats.values()),
            }
        )

    async def _compute_variant_stats(
        self,
        exp: Experiment,
        variant_name: str,
        attribution_hours: int,
        outcome_events: list[str],
    ) -> dict:
        # Get all users in this variant
        exposures = await self.db.execute(
            select(Exposure).where(
                Exposure.experiment_id == exp.id,
                Exposure.variant_name == variant_name,
            )
        )
        exp_rows = exposures.scalars().all()
        user_ids = [e.user_id for e in exp_rows]
        exposure_map = {e.user_id: e for e in exp_rows}
        num_users = len(user_ids)

        if num_users == 0:
            return {
                "users": 0,
                "llm_calls": 0,
                "avg_cost_per_call": None,
                "total_cost": None,
                "avg_latency_ms": None,
                "p50_latency_ms": None,
                "avg_input_tokens": None,
                "avg_output_tokens": None,
                "conversions": 0,
                "conversion_rate": 0.0,
                "cost_per_conversion": None,
            }

        # Get traces and spans
        traces_result = await self.db.execute(
            select(Trace).where(Trace.user_id.in_(user_ids))
        )
        traces = traces_result.scalars().all()
        trace_ids = [t.id for t in traces]

        spans_result = await self.db.execute(
            select(Span).where(
                Span.trace_id.in_(trace_ids),
                Span.type == "llm",
            )
        ) if trace_ids else None

        spans = spans_result.scalars().all() if spans_result else []
        llm_calls = len(spans)
        costs = [float(s.cost_usd) for s in spans if s.cost_usd is not None]
        latencies = [s.latency_ms for s in spans]
        input_tokens = [s.input_tokens for s in spans if s.input_tokens is not None]
        output_tokens = [s.output_tokens for s in spans if s.output_tokens is not None]

        avg_cost = sum(costs) / len(costs) if costs else None
        total_cost = sum(costs) if costs else None
        avg_latency = sum(latencies) / len(latencies) if latencies else None
        p50_latency = sorted(latencies)[len(latencies) // 2] if latencies else None
        avg_input = sum(input_tokens) / len(input_tokens) if input_tokens else None
        avg_output = sum(output_tokens) / len(output_tokens) if output_tokens else None

        # Count conversions (within attribution window)
        conversions = 0
        if outcome_events and user_ids:
            for uid in user_ids:
                exposure = exposure_map[uid]
                from datetime import timedelta
                window_end = exposure.exposed_at + timedelta(hours=attribution_hours)
                outcome_result = await self.db.execute(
                    select(Outcome).where(
                        Outcome.user_id == uid,
                        Outcome.event_name.in_(outcome_events),
                        Outcome.created_at >= exposure.exposed_at,
                        Outcome.created_at <= window_end,
                    )
                )
                if outcome_result.scalars().first():
                    conversions += 1

        conversion_rate = conversions / num_users if num_users > 0 else 0.0
        cost_per_conversion = (
            (total_cost / conversions) if total_cost and conversions > 0 else None
        )

        return {
            "users": num_users,
            "llm_calls": llm_calls,
            "avg_cost_per_call": round(avg_cost, 6) if avg_cost is not None else None,
            "total_cost": round(total_cost, 6) if total_cost is not None else None,
            "avg_latency_ms": round(avg_latency, 1) if avg_latency is not None else None,
            "p50_latency_ms": p50_latency,
            "avg_input_tokens": round(avg_input, 1) if avg_input is not None else None,
            "avg_output_tokens": round(avg_output, 1) if avg_output is not None else None,
            "conversions": conversions,
            "conversion_rate": round(conversion_rate, 4),
            "cost_per_conversion": round(cost_per_conversion, 6) if cost_per_conversion else None,
        }

    def _generate_recommendation(
        self,
        variant_stats: dict,
        current_name: Optional[str],
        outcome_events: list[str],
    ) -> Optional[dict]:
        if not current_name or not outcome_events:
            return None

        current = variant_stats.get(current_name, {})
        best_challenger = None
        best_lift = 0.0

        for name, stats in variant_stats.items():
            if name == current_name:
                continue
            if not stats.get("is_significant"):
                continue
            lift = stats.get("conversion_rate", 0) - current.get("conversion_rate", 0)
            if lift > best_lift:
                best_lift = lift
                best_challenger = (name, stats)

        if not best_challenger:
            return {"action": "continue", "message": "No statistically significant improvements found yet."}

        name, stats = best_challenger
        lift_pct = best_lift / max(current.get("conversion_rate", 1), 0.001) * 100

        curr_cost = current.get("avg_cost_per_call") or 0
        chal_cost = stats.get("avg_cost_per_call") or 0
        monthly_calls_estimate = (stats.get("users", 0) + current.get("users", 0)) * 30

        cost_delta_monthly = (chal_cost - curr_cost) * monthly_calls_estimate

        return {
            "action": "switch",
            "variant": name,
            "lift_pct": round(lift_pct, 1),
            "p_value": stats.get("p_value"),
            "cost_delta_monthly_usd": round(cost_delta_monthly, 2),
            "message": (
                f"Switch to {name}: +{lift_pct:.1f}% conversion rate "
                f"(p={stats.get('p_value', 'N/A'):.3f})"
            ),
        }
