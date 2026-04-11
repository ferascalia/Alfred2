"""FastAPI application — webhook + healthz + jobs endpoints."""
import json
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from telegram import Update

from alfred.bot.app import build_application
from alfred.config import settings
from alfred.logging import setup_logging

log = structlog.get_logger()

_ptb_app = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _ptb_app
    setup_logging()

    _ptb_app = build_application()
    await _ptb_app.initialize()

    # Register webhook
    webhook_url = f"{settings.webhook_url}/webhook"
    await _ptb_app.bot.set_webhook(
        url=webhook_url,
        secret_token=settings.webhook_secret or None,
        allowed_updates=["message", "callback_query"],
    )
    log.info("webhook.registered", url=webhook_url)

    yield

    await _ptb_app.shutdown()
    log.info("app.shutdown")


app = FastAPI(title="Alfred", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    # Validate Telegram webhook secret
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if settings.webhook_secret and not secrets.compare_digest(secret, settings.webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid secret")

    body = await request.body()
    update = Update.de_json(json.loads(body), _ptb_app.bot)  # type: ignore[union-attr]

    await _ptb_app.process_update(update)  # type: ignore[union-attr]

    return Response(status_code=200)


def _check_jobs_secret(x_jobs_secret: str = Header(default="")) -> None:
    if settings.jobs_secret and not secrets.compare_digest(x_jobs_secret, settings.jobs_secret):
        raise HTTPException(status_code=403, detail="Invalid jobs secret")


@app.post("/jobs/nudge", dependencies=[Depends(_check_jobs_secret)])
async def jobs_nudge(request: Request) -> dict[str, object]:
    body = await request.json()
    contact_id: str = body.get("contact_id", "")
    if not contact_id:
        raise HTTPException(status_code=400, detail="contact_id required")

    from alfred.jobs.nudge import process_nudge
    result = await process_nudge(contact_id=contact_id)
    return result


@app.post("/jobs/digest", dependencies=[Depends(_check_jobs_secret)])
async def jobs_digest(request: Request) -> dict[str, object]:
    body = await request.json()
    user_id: str = body.get("user_id", "")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    from alfred.jobs.digest import process_digest
    result = await process_digest(user_id=user_id)
    return result
