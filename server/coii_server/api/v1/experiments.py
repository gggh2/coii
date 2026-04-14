"""Experiment management endpoints."""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from coii_server.db import get_db
from coii_server.activities import ExperimentActivity, AnalysisActivity

router = APIRouter(prefix="/experiments")


class VariantCreate(BaseModel):
    name: str
    provider: str
    model: str
    prompt_version: Optional[str] = None
    config: dict = {}
    traffic_pct: int
    is_current: bool = False


class ExperimentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    variants: List[VariantCreate]
    outcome_events: List[str] = []
    attribution_window_hours: int = 168

    @field_validator("variants")
    @classmethod
    def validate_variants(cls, v):
        total = sum(var.traffic_pct for var in v)
        if total != 100:
            raise ValueError(f"Variant traffic_pct must sum to 100, got {total}")
        return v


class ExperimentUpdate(BaseModel):
    description: Optional[str] = None
    variants: Optional[List[VariantCreate]] = None
    outcome_events: Optional[List[str]] = None
    attribution_window_hours: Optional[int] = None
    status: Optional[str] = None


class SwitchRequest(BaseModel):
    variant_name: str


def _exp_to_dict(exp) -> dict:
    return {
        "id": exp.public_id,
        "name": exp.name,
        "description": exp.description,
        "status": exp.status,
        "variants": exp.variants,
        "outcome_events": exp.outcome_events,
        "attribution_window_hours": exp.attribution_window_hours,
        "created_at": exp.created_at.isoformat() if exp.created_at else None,
        "updated_at": exp.updated_at.isoformat() if exp.updated_at else None,
        "started_at": exp.started_at.isoformat() if exp.started_at else None,
        "stopped_at": exp.stopped_at.isoformat() if exp.stopped_at else None,
    }


@router.post("", status_code=201)
async def create_experiment(body: ExperimentCreate, db: AsyncSession = Depends(get_db)):
    activity = ExperimentActivity(db)
    r = await activity.create(
        name=body.name,
        variants=[v.model_dump() for v in body.variants],
        outcome_events=body.outcome_events,
        description=body.description,
        attribution_window_hours=body.attribution_window_hours,
    )
    if not r.ok:
        raise HTTPException(
            status_code=409 if r.code == "DUPLICATE_NAME" else 400,
            detail=r.message,
        )
    return _exp_to_dict(r.value)


@router.get("")
async def list_experiments(db: AsyncSession = Depends(get_db)):
    activity = ExperimentActivity(db)
    r = await activity.list_all()
    return [_exp_to_dict(e) for e in r.value]


@router.get("/{name}")
async def get_experiment(name: str, db: AsyncSession = Depends(get_db)):
    activity = ExperimentActivity(db)
    r = await activity.get_by_name(name)
    if not r.ok:
        raise HTTPException(404, r.message)
    return _exp_to_dict(r.value)


@router.patch("/{name}")
async def update_experiment(name: str, body: ExperimentUpdate, db: AsyncSession = Depends(get_db)):
    activity = ExperimentActivity(db)
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    if "variants" in kwargs:
        kwargs["variants"] = [v for v in kwargs["variants"]]
    r = await activity.update(name, **kwargs)
    if not r.ok:
        raise HTTPException(404 if r.code == "NOT_FOUND" else 400, r.message)
    return _exp_to_dict(r.value)


@router.post("/{name}/start")
async def start_experiment(name: str, db: AsyncSession = Depends(get_db)):
    activity = ExperimentActivity(db)
    r = await activity.start(name)
    if not r.ok:
        raise HTTPException(404 if r.code == "NOT_FOUND" else 400, r.message)
    return _exp_to_dict(r.value)


@router.post("/{name}/stop")
async def stop_experiment(name: str, db: AsyncSession = Depends(get_db)):
    activity = ExperimentActivity(db)
    r = await activity.stop(name)
    if not r.ok:
        raise HTTPException(404 if r.code == "NOT_FOUND" else 400, r.message)
    return _exp_to_dict(r.value)


@router.post("/{name}/switch")
async def switch_experiment(name: str, body: SwitchRequest, db: AsyncSession = Depends(get_db)):
    activity = ExperimentActivity(db)
    r = await activity.switch(name, body.variant_name)
    if not r.ok:
        raise HTTPException(404 if r.code == "NOT_FOUND" else 400, r.message)
    return _exp_to_dict(r.value)


@router.get("/{name}/results")
async def get_experiment_results(name: str, db: AsyncSession = Depends(get_db)):
    activity = AnalysisActivity(db)
    r = await activity.get_results(name)
    if not r.ok:
        raise HTTPException(404, r.message)
    return r.value
