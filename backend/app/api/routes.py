"""HTTP controllers — webhook ingest + simple status endpoints.

Stays thin: pulls payload, calls Activity, maps Result to HTTP status.
Webhook handler returns 200 fast and processes asynchronously so the
tracker doesn't time out and retry on slow LLM calls.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Header, Request

from app.activities.handle_event import handle_linear_event

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ping")
async def ping():
    return {"pong": True}


@router.post("/webhooks/linear")
async def linear_webhook(
    request: Request,
    linear_signature: str | None = Header(default=None, alias="Linear-Signature"),
    linear_delivery: str | None = Header(default=None, alias="Linear-Delivery"),
):
    raw_body = await request.body()
    log.info(
        "linear webhook received: delivery=%s bytes=%d",
        linear_delivery, len(raw_body),
    )
    if log.isEnabledFor(logging.DEBUG):
        log.debug("payload: %s", raw_body.decode("utf-8", errors="replace"))
    asyncio.create_task(_dispatch(raw_body, linear_signature))
    return {"ok": True}


async def _dispatch(raw_body: bytes, signature: str | None) -> None:
    try:
        result = await handle_linear_event(raw_body, signature)
        if not result.ok:
            log.warning("handle_linear_event returned Err: %s — %s", result.code, result.message)
    except BaseException:
        log.exception("unhandled error in webhook dispatch")
