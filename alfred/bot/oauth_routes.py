"""OAuth FastAPI routes — provider-parameterized OAuth flow."""

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


def _sign_state(telegram_id: int, provider_slug: str) -> str:
    payload = f"{provider_slug}:{telegram_id}"
    sig = hmac.new(_STATE_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:12]
    return f"{payload}.{sig}"


def _verify_state(state: str) -> tuple[str | None, int | None]:
    if "." not in state:
        return None, None
    payload, sig = state.rsplit(".", 1)
    expected = hmac.new(_STATE_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:12]
    if not hmac.compare_digest(sig, expected):
        return None, None
    if ":" not in payload:
        return None, None
    provider_slug, tg_id_str = payload.split(":", 1)
    try:
        return provider_slug, int(tg_id_str)
    except ValueError:
        return None, None


@router.get("/{provider_slug}/start")
async def oauth_start(provider_slug: str, request: Request) -> HTMLResponse:
    telegram_id = request.query_params.get("telegram_id")
    if not telegram_id:
        raise HTTPException(status_code=400, detail="telegram_id required")

    try:
        tg_id = int(telegram_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid telegram_id")

    from alfred.integrations import get_provider

    provider = get_provider(provider_slug)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_slug}' not found")

    state = _sign_state(tg_id, provider_slug)
    auth_url = provider.build_auth_url(state)
    display_name = provider.info().display_name

    return HTMLResponse(
        f'<html><head><meta http-equiv="refresh" content="0;url={auth_url}"></head>'
        f'<body>Redirecionando para {display_name}...</body></html>'
    )


@router.get("/{provider_slug}/callback")
async def oauth_callback(provider_slug: str, request: Request) -> HTMLResponse:
    error = request.query_params.get("error")
    if error:
        log.warning("oauth.callback_error", provider=provider_slug, error=error)
        return HTMLResponse(
            "<html><body><h2>Autorização cancelada</h2>"
            "<p>Você pode fechar esta janela e tentar novamente no Telegram com /connect.</p>"
            "</body></html>"
        )

    code = request.query_params.get("code")
    state = request.query_params.get("state", "")

    if not code:
        raise HTTPException(status_code=400, detail="code required")

    verified_provider, telegram_id = _verify_state(state)
    if not telegram_id or verified_provider != provider_slug:
        raise HTTPException(status_code=400, detail="invalid state")

    from alfred.integrations import get_provider

    provider = get_provider(provider_slug)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_slug}' not found")

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

    from alfred.services.oauth import store_tokens

    try:
        token_data = await provider.exchange_code(code, state)
    except Exception as exc:
        log.error(
            "oauth.token_exchange_failed",
            provider=provider_slug,
            telegram_id=telegram_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return HTMLResponse(
            "<html><body><h2>Erro na autenticação</h2>"
            f"<p>Falha no token exchange: {type(exc).__name__}</p>"
            "<p>Tente novamente com /connect.</p>"
            "</body></html>"
        )

    try:
        await store_tokens(user_id, provider_slug, token_data)
    except Exception as exc:
        log.error(
            "oauth.store_tokens_failed",
            provider=provider_slug,
            telegram_id=telegram_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return HTMLResponse(
            "<html><body><h2>Erro na autenticação</h2>"
            f"<p>Falha ao salvar tokens: {type(exc).__name__}</p>"
            "<p>Tente novamente com /connect.</p>"
            "</body></html>"
        )

    display_name = provider.info().display_name
    log.info("oauth.connected", provider=provider_slug, telegram_id=telegram_id, user_id=user_id)

    await _notify_telegram(telegram_id, display_name)

    return HTMLResponse(
        "<html><body>"
        f"<h2>{display_name} conectado!</h2>"
        "<p>Pode fechar esta janela e voltar ao Telegram.</p>"
        "</body></html>"
    )


async def _notify_telegram(telegram_id: int, provider_display_name: str) -> None:
    try:
        import httpx

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={
                "chat_id": telegram_id,
                "text": (
                    f"✅ {provider_display_name} conectado com sucesso!\n\n"
                    "Agora você pode me pedir coisas como:\n"
                    '• "O que tenho na agenda amanhã?"\n'
                    '• "Marca reunião com João quinta às 15h"\n'
                    '• "Minha agenda da semana"'
                ),
            })
    except Exception:
        log.exception("oauth.telegram_notify_failed", telegram_id=telegram_id)
