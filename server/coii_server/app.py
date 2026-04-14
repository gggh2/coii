"""FastAPI application factory."""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from coii_server.api import api_router
from coii_server.db import init_db


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db()
        yield

    app = FastAPI(
        title="Coii",
        description="Open-source LLM experimentation platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    # Serve React SPA (built frontend)
    static_dir = Path(__file__).parent / "static"
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/experiments", include_in_schema=False)
    @app.get("/experiments/{rest:path}", include_in_schema=False)
    @app.get("/pricing", include_in_schema=False)
    async def serve_spa(rest: str = ""):
        index = static_dir / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"message": "Coii API running. Build frontend with: cd frontend && npm run build", "docs": "/docs"}

    return app


app = create_app()
