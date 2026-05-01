"""Standard ops endpoints: /health, /cron/status, /cron/run/{name}."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.scheduler import TrackedScheduler


def make_ops_router(service_name: str, scheduler: TrackedScheduler) -> APIRouter:
    router = APIRouter(tags=["ops"])

    @router.get("/health")
    async def health():
        return {"status": "ok", "service": service_name}

    @router.get("/cron/status")
    async def cron_status():
        return {"service": service_name, "jobs": scheduler.status()}

    @router.post("/cron/run/{name}")
    async def cron_run(name: str):
        try:
            await scheduler.run_now(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"No job named '{name}'")
        return {"ok": True, "triggered": name}

    return router
