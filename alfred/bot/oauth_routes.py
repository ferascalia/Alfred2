"""OAuth FastAPI routes — handles Google OAuth flow initiated from Telegram /connect."""

import hashlib
import hmac

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from alfred.config import settings
from alfred.db.client import get_db

log = structlog.get_logger()

router = APIRouter(prefix="/oauth")

_STATE_SECRET = (settings.webhook_secret or settings.jobs_secret or "alfred-dev").encode()


def _sign_state(telegram_id: int) -> str:
    payload = str(telegram_id)
    sig = hmac.new(_STATE_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:12]
    return f"{payload}.{sig}"


def _verify_state(state: str) -> int | None:
    if "." not in state:
        return None
    payload, sig = state.rsplit(".", 1)
    expected = hmac.new(_STATE_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:12]
    if hmac.compare_digest(sig, expected):
        return int(payload)
    return None


@router.get("/google")
async def google_auth_start(request: Request) -> HTMLResponse:
    telegram_id = request.query_params.get("telegram_id")
    if not telegram_id:
        raise HTTPException(status_code=400, detail="telegram_id required")

    try:
        tg_id = int(telegram_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid telegram_id")

    from alfred.services.oauth import build_google_auth_url

    state = _sign_state(tg_id)
    auth_url = build_google_auth_url(state)

    return HTMLResponse(
        f'<html><head><meta http-equiv="refresh" content="0;url={auth_url}"></head>'
        f'<body>Redirecionando para Google...</body></html>'
    )


@router.get("/google/callback")
async def google_auth_callback(request: Request) -> HTMLResponse:
    code = request.query_params.get("code")
    state = request.query_params.get("state", "")
    error = request.query_params.get("error")

    if error:
        log.warning("oauth.callback_error", error=error)
        return HTMLResponse(
            "<html><body><h2>Autorização cancelada</h2>"
            "<p>Você pode fechar esta janela e tentar novamente no Telegram com /connect.</p>"
            "</body></html>"
        )

    if not code:
        raise HTTPException(status_code=400, detail="code required")

    telegram_id = _verify_state(state)
    if not telegram_id:
        raise HTTPException(status_code=400, detail="invalid state")

    db = get_db()
    user_result = (
        db.table("users")
        .select("id")
        .eq("telegram_id", telegram_id)
        .single()
        .execute()
    )
    if not user_result.data:
        raise HTTPException(status_code=404, detail="user not found — use /start first")

    user_id = user_result.data["id"]

    from alfred.services.oauth import exchange_google_code, store_tokens

    try:
        creds = await exchange_google_code(code)
        await store_tokens(user_id, "google", creds)
    except Exception:
        log.exception("oauth.exchange_failed", telegram_id=telegram_id)
        return HTMLResponse(
            "<html><body><h2>Erro na autenticação</h2>"
            "<p>Não foi possível completar a conexão. Tente novamente com /connect.</p>"
            "</body></html>"
        )

    log.info("oauth.google_connected", telegram_id=telegram_id, user_id=user_id)

    await _notify_telegram(telegram_id)

    return HTMLResponse(
        "<html><body>"
        "<h2>Google Calendar conectado!</h2>"
        "<p>Pode fechar esta janela e voltar ao Telegram.</p>"
        "</body></html>"
    )


async def _notify_telegram(telegram_id: int) -> None:
    try:
        import httpx

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={
                "chat_id": telegram_id,
                "text": (
                    "Google Calendar conectado com sucesso!\n\n"
                    "Agora você pode me pedir coisas como:\n"
                    '• "O que tenho na agenda amanhã?"\n'
                    '• "Marca reunião com João quinta às 15h"\n'
                    '• "Minha agenda da semana"'
                ),
                "parse_mode": "Markdown",
            })
    except Exception:
        log.exception("oauth.telegram_notify_failed", telegram_id=telegram_id)
