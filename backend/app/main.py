"""Entry point for coii — Personal Agent Workforce backend.

Receives tracker webhooks (Linear in Phase 1), matches them against
user-defined triggers, loads the corresponding Agent workspace,
and dispatches to the configured runtime (claude_code CLI by default;
falls back to anthropic SDK or templated reply).

Note on event loop: we force the standard asyncio loop instead of
uvloop because asyncio.create_subprocess_exec under uvloop has been
observed to deadlock when spawning the `claude` CLI on macOS — the
child runs but never reports output back. The standard loop's child
watcher works correctly.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

# Must be set before any uvloop import path runs.
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

from fastapi import FastAPI

from app import config  # noqa: E402

# Initialize config + populate os.environ from the dotenv chain before any
# downstream module reads env vars. config.get() is idempotent.
_cfg = config.get()

from app.api.admin import router as admin_router  # noqa: E402
from app.api.routes import router as api_router  # noqa: E402
from app.ops import make_ops_router  # noqa: E402
from app.poller import LinearPoller  # noqa: E402
from app.scheduler import TrackedScheduler  # noqa: E402

# LOG_LEVEL env still wins as a transitional override; otherwise the level
# in config.json's `service.log_level` is authoritative.
logging.basicConfig(
    level=(os.getenv("LOG_LEVEL") or _cfg.service.log_level).upper(),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    force=True,
)
log = logging.getLogger(__name__)

SERVICE_NAME = os.getenv("SERVICE_NAME") or _cfg.service.name

scheduler = TrackedScheduler(SERVICE_NAME)


def _maybe_register_linear_poller() -> None:
    """Schedule a Linear polling job if team keys are configured.

    Source of truth is ``trackers.linear.team_keys`` in config.json, with an
    optional ``LINEAR_TEAM_KEYS`` env override (comma-separated). Polling is
    the no-gateway alternative to webhooks: outbound HTTPS only, works behind
    any firewall, no public URL or tunnel needed. Same downstream pipeline
    (matcher → trigger → agent) as the webhook path.
    """
    cfg = config.get().linear
    raw_env = os.getenv("LINEAR_TEAM_KEYS", "").strip()
    if raw_env:
        team_keys = tuple(k.strip().upper() for k in raw_env.split(",") if k.strip())
    else:
        team_keys = cfg.team_keys

    if not team_keys:
        log.info("no Linear team keys configured — polling disabled")
        return

    interval = max(10, cfg.poll_interval_seconds)
    poller = LinearPoller(team_keys=team_keys)

    @scheduler.interval("linear_poll", seconds=interval)
    async def _job() -> None:
        await poller.poll_once()

    log.info(
        "linear poller registered: teams=%s every %ds",
        list(team_keys), interval,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting %s", SERVICE_NAME)
    _maybe_register_linear_poller()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)
app.include_router(api_router)
app.include_router(admin_router)
app.include_router(make_ops_router(SERVICE_NAME, scheduler))
