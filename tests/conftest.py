"""Shared test fixtures."""
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

# Use in-memory SQLite for tests
import os
os.environ["COII_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def app():
    """Create a fresh app instance with in-memory DB."""
    from coii_server.app import create_app
    application = create_app()
    # Trigger startup
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        # Startup happens on first request handled by lifespan
        pass
    return application


@pytest.fixture(scope="session")
async def client(app):
    """HTTP test client."""
    from coii_server.db import init_db
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
