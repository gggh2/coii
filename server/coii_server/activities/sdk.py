"""SDK-facing business logic: assignments, traces, spans, outcomes."""
import hashlib
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from coii_server.models.orm import Experiment, Exposure, Trace, Span, Outcome, ModelPricing
from coii_server.utils import make_public_id, Ok, Err, Result


def _assign_variant(variants: list[dict], user_id: str, experiment_name: str) -> dict:
    """Deterministic variant assignment via hashing."""
    h = hashlib.md5(f"{experiment_name}:{user_id}".encode()).hexdigest()
    bucket = int(h, 16) % 100
    cumulative = 0
    for v in variants:
        cumulative += v.get("traffic_pct", 0)
        if bucket < cumulative:
            return v
    return variants[-1]


class SDKActivity:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_assignments(self, user_id: str) -> Result:
        """Get or create exposures for all running experiments."""
        running_result = await self.db.execute(
            select(Experiment).where(Experiment.status == "running")
        )
        experiments = running_result.scalars().all()

        assignments = {}
        for exp in experiments:
            # Check existing exposure
            exposure = await self.db.scalar(
                select(Exposure).where(
                    and_(
                        Exposure.experiment_id == exp.id,
                        Exposure.user_id == user_id,
                    )
                )
            )
            if not exposure:
                variant = _assign_variant(exp.variants, user_id, exp.name)
                exposure = Exposure(
                    public_id=make_public_id("exposure"),
                    experiment_id=exp.id,
                    user_id=user_id,
                    variant_name=variant["name"],
                )
                self.db.add(exposure)
                await self.db.flush()

            # Find the variant config
            variant_config = next(
                (v for v in exp.variants if v["name"] == exposure.variant_name),
                None,
            )
            assignments[exp.name] = {
                "experiment_id": exp.public_id,
                "experiment_name": exp.name,
                "variant": variant_config,
                "exposure_id": exposure.public_id,
            }

        return Ok(assignments)

    async def create_trace(
        self,
        public_id: str,
        user_id: str,
        session_id: Optional[str] = None,
        name: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Result:
        trace = Trace(
            public_id=public_id,
            user_id=user_id,
            session_id=session_id,
            name=name,
            metadata_=metadata or {},
        )
        self.db.add(trace)
        await self.db.flush()
        return Ok(trace)

    async def end_trace(self, trace_public_id: str) -> Result:
        trace = await self.db.scalar(
            select(Trace).where(Trace.public_id == trace_public_id)
        )
        if not trace:
            return Err("NOT_FOUND", f"Trace '{trace_public_id}' not found")
        trace.ended_at = datetime.now(timezone.utc)
        await self.db.flush()
        return Ok(trace)

    async def create_span(
        self,
        trace_public_id: str,
        type: str,
        latency_ms: int,
        model: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        name: Optional[str] = None,
        status: str = "success",
        metadata: Optional[dict] = None,
    ) -> Result:
        trace = await self.db.scalar(
            select(Trace).where(Trace.public_id == trace_public_id)
        )
        if not trace:
            return Err("NOT_FOUND", f"Trace '{trace_public_id}' not found")

        # Compute cost
        cost_usd = None
        if type == "llm" and model and input_tokens is not None and output_tokens is not None:
            cost_usd = await self._compute_cost(trace, model, input_tokens, output_tokens)

        span = Span(
            public_id=make_public_id("span"),
            trace_id=trace.id,
            type=type,
            name=name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            status=status,
            metadata_=metadata or {},
        )
        self.db.add(span)
        await self.db.flush()
        return Ok(span)

    async def _compute_cost(
        self, trace: Trace, model: str, input_tokens: int, output_tokens: int
    ) -> Optional[float]:
        """Compute cost via variant's provider + model → pricing_key → pricing table."""
        # Find the exposure for this trace's user_id to get provider
        provider = await self._get_provider_for_trace(trace)
        
        if provider:
            pricing_key = f"{provider}/{model}"
        else:
            # Fallback: try to infer from model name
            pricing_key = model

        # Try user override first, then builtin
        pricing = await self.db.scalar(
            select(ModelPricing)
            .where(ModelPricing.pricing_key == pricing_key)
            .order_by(ModelPricing.source.desc())  # 'user' > 'builtin'
        )
        if not pricing:
            # Try just the model as key
            pricing = await self.db.scalar(
                select(ModelPricing).where(ModelPricing.pricing_key == model)
            )
        if not pricing:
            return None

        cost = (
            input_tokens / 1_000_000 * float(pricing.input_cost_per_mtok)
            + output_tokens / 1_000_000 * float(pricing.output_cost_per_mtok)
        )
        return cost

    async def _get_provider_for_trace(self, trace: Trace) -> Optional[str]:
        """Find the variant provider from active experiment exposures."""
        exposures = await self.db.execute(
            select(Exposure, Experiment)
            .join(Experiment, Exposure.experiment_id == Experiment.id)
            .where(Exposure.user_id == trace.user_id)
            .where(Experiment.status.in_(["running", "completed"]))
            .order_by(Exposure.exposed_at.desc())
        )
        rows = exposures.all()
        for exposure, experiment in rows:
            variant = next(
                (v for v in experiment.variants if v["name"] == exposure.variant_name),
                None,
            )
            if variant and variant.get("provider"):
                return variant["provider"]
        return None

    async def record_outcome(
        self,
        user_id: str,
        event_name: str,
        properties: Optional[dict] = None,
    ) -> Result:
        outcome = Outcome(
            public_id=make_public_id("outcome"),
            user_id=user_id,
            event_name=event_name,
            properties=properties or {},
        )
        self.db.add(outcome)
        await self.db.flush()
        return Ok(outcome)
