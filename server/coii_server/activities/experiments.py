"""Experiment management business logic."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from coii_server.models.orm import Experiment
from coii_server.utils import make_public_id, Ok, Err, Result


class ExperimentActivity:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        name: str,
        variants: list[dict],
        outcome_events: list[str],
        description: Optional[str] = None,
        attribution_window_hours: int = 168,
    ) -> Result:
        # Validate variants traffic
        total_pct = sum(v.get("traffic_pct", 0) for v in variants)
        if total_pct != 100:
            return Err("INVALID_TRAFFIC", f"Variant traffic must sum to 100, got {total_pct}")
        
        current_count = sum(1 for v in variants if v.get("is_current"))
        if current_count > 1:
            return Err("INVALID_VARIANTS", "Only one variant can be marked as current")

        # Check name uniqueness
        existing = await self.db.scalar(
            select(Experiment).where(Experiment.name == name)
        )
        if existing:
            return Err("DUPLICATE_NAME", f"Experiment '{name}' already exists")

        exp = Experiment(
            public_id=make_public_id("experiment"),
            name=name,
            description=description,
            variants=variants,
            outcome_events=outcome_events,
            attribution_window_hours=attribution_window_hours,
            status="draft",
        )
        self.db.add(exp)
        await self.db.flush()
        return Ok(exp)

    async def list_all(self) -> Result:
        result = await self.db.execute(
            select(Experiment).order_by(Experiment.created_at.desc())
        )
        return Ok(result.scalars().all())

    async def get_by_name(self, name: str) -> Result:
        exp = await self.db.scalar(
            select(Experiment).where(Experiment.name == name)
        )
        if not exp:
            return Err("NOT_FOUND", f"Experiment '{name}' not found")
        return Ok(exp)

    async def get_by_public_id(self, public_id: str) -> Result:
        exp = await self.db.scalar(
            select(Experiment).where(Experiment.public_id == public_id)
        )
        if not exp:
            return Err("NOT_FOUND", f"Experiment not found")
        return Ok(exp)

    async def update(self, name: str, **kwargs) -> Result:
        r = await self.get_by_name(name)
        if not r.ok:
            return r
        exp = r.value

        allowed = {"description", "variants", "outcome_events", "attribution_window_hours", "status"}
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                setattr(exp, k, v)
        exp.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return Ok(exp)

    async def start(self, name: str) -> Result:
        r = await self.get_by_name(name)
        if not r.ok:
            return r
        exp = r.value
        if exp.status not in ("draft", "paused"):
            return Err("INVALID_STATE", f"Cannot start experiment in state '{exp.status}'")
        exp.status = "running"
        exp.started_at = datetime.now(timezone.utc)
        exp.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return Ok(exp)

    async def stop(self, name: str) -> Result:
        r = await self.get_by_name(name)
        if not r.ok:
            return r
        exp = r.value
        if exp.status != "running":
            return Err("INVALID_STATE", f"Experiment is not running")
        exp.status = "completed"
        exp.stopped_at = datetime.now(timezone.utc)
        exp.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return Ok(exp)

    async def switch(self, name: str, variant_name: str) -> Result:
        """Mark a variant as 'current' and stop the experiment."""
        r = await self.get_by_name(name)
        if not r.ok:
            return r
        exp = r.value

        variant_names = [v["name"] for v in exp.variants]
        if variant_name not in variant_names:
            return Err("NOT_FOUND", f"Variant '{variant_name}' not found")

        new_variants = []
        for v in exp.variants:
            v = dict(v)
            v["is_current"] = v["name"] == variant_name
            new_variants.append(v)
        exp.variants = new_variants
        exp.status = "completed"
        exp.stopped_at = datetime.now(timezone.utc)
        exp.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return Ok(exp)

    async def list_running(self) -> Result:
        result = await self.db.execute(
            select(Experiment).where(Experiment.status == "running")
        )
        return Ok(result.scalars().all())
