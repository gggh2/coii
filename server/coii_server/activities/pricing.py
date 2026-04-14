"""Pricing management business logic."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from coii_server.models.orm import ModelPricing
from coii_server.utils import Ok, Err, Result


class PricingActivity:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> Result:
        result = await self.db.execute(
            select(ModelPricing).order_by(ModelPricing.pricing_key)
        )
        return Ok(result.scalars().all())

    async def upsert(
        self,
        pricing_key: str,
        input_cost_per_mtok: float,
        output_cost_per_mtok: float,
        source: str = "user",
    ) -> Result:
        existing = await self.db.scalar(
            select(ModelPricing).where(ModelPricing.pricing_key == pricing_key)
        )
        if existing:
            existing.input_cost_per_mtok = input_cost_per_mtok
            existing.output_cost_per_mtok = output_cost_per_mtok
            existing.source = source
            existing.updated_at = datetime.now(timezone.utc)
            await self.db.flush()
            return Ok(existing)
        else:
            pricing = ModelPricing(
                pricing_key=pricing_key,
                input_cost_per_mtok=input_cost_per_mtok,
                output_cost_per_mtok=output_cost_per_mtok,
                source=source,
            )
            self.db.add(pricing)
            await self.db.flush()
            return Ok(pricing)

    async def delete(self, pricing_key: str) -> Result:
        pricing = await self.db.scalar(
            select(ModelPricing).where(ModelPricing.pricing_key == pricing_key)
        )
        if not pricing:
            return Err("NOT_FOUND", f"Pricing for '{pricing_key}' not found")
        if pricing.source == "builtin":
            return Err("FORBIDDEN", "Cannot delete built-in pricing. Override it instead.")
        await self.db.delete(pricing)
        await self.db.flush()
        return Ok({"deleted": pricing_key})
