"""Pricing management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from coii_server.db import get_db
from coii_server.activities import PricingActivity

router = APIRouter(prefix="/pricing")


class PricingUpsert(BaseModel):
    pricing_key: str
    input_cost_per_mtok: float
    output_cost_per_mtok: float


def _pricing_to_dict(p) -> dict:
    return {
        "pricing_key": p.pricing_key,
        "input_cost_per_mtok": float(p.input_cost_per_mtok),
        "output_cost_per_mtok": float(p.output_cost_per_mtok),
        "source": p.source,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("")
async def list_pricing(db: AsyncSession = Depends(get_db)):
    activity = PricingActivity(db)
    r = await activity.list_all()
    return [_pricing_to_dict(p) for p in r.value]


@router.put("/{pricing_key:path}")
async def upsert_pricing(pricing_key: str, body: PricingUpsert, db: AsyncSession = Depends(get_db)):
    activity = PricingActivity(db)
    r = await activity.upsert(
        pricing_key=pricing_key,
        input_cost_per_mtok=body.input_cost_per_mtok,
        output_cost_per_mtok=body.output_cost_per_mtok,
        source="user",
    )
    if not r.ok:
        raise HTTPException(400, r.message)
    return _pricing_to_dict(r.value)


@router.delete("/{pricing_key:path}", status_code=204)
async def delete_pricing(pricing_key: str, db: AsyncSession = Depends(get_db)):
    activity = PricingActivity(db)
    r = await activity.delete(pricing_key)
    if not r.ok:
        raise HTTPException(404 if r.code == "NOT_FOUND" else 403, r.message)
