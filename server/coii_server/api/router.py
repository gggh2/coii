from fastapi import APIRouter
from .v1 import experiments, sdk, pricing, registry

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(experiments.router, tags=["experiments"])
api_router.include_router(sdk.router, tags=["sdk"])
api_router.include_router(pricing.router, tags=["pricing"])
api_router.include_router(registry.router, tags=["registry"])
