"""Access control — whitelist and invite codes for multi-tenant onboarding."""

import secrets
import string
from functools import wraps

import structlog

from alfred.config import settings
from alfred.db.client import get_db

log = structlog.get_logger()

_ACCESS_DENIED_MSG = (
    "O Alfred está em beta fechado no momento.\n\n"
    "Use /start para solicitar acesso."
)


def _get_whitelist() -> set[int]:
    raw = settings.allowed_telegram_ids
    if not raw:
        return set()
    return {int(tid.strip()) for tid in raw.split(",") if tid.strip().isdigit()}


async def check_access(telegram_id: int) -> bool:
    whitelist = _get_whitelist()
    if not whitelist:
        log.warning("access.no_whitelist_configured")
        return False
    if telegram_id in whitelist:
        return True

    db = get_db()
    result = db.table("users").select("id").eq("telegram_id", telegram_id).execute()
    if result.data:
        return True

    return False


def require_access(handler):  # type: ignore[no-untyped-def]
    """Decorator that blocks handlers for unauthorized Telegram users."""

    @wraps(handler)
    async def wrapper(update, context):  # type: ignore[no-untyped-def]
        if not update.effective_user:
            return
        has_access = await check_access(update.effective_user.id)
        if not has_access:
            log.warning("access.denied", telegram_id=update.effective_user.id)
            if update.message:
                await update.message.reply_text(_ACCESS_DENIED_MSG)
            return
        return await handler(update, context)

    return wrapper


async def validate_invite_code(code: str) -> dict | None:
    db = get_db()
    result = (
        db.table("invite_codes")
        .select("*")
        .eq("code", code.strip().upper())
        .is_("used_by", "null")
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


async def use_invite_code(code: str, user_id: str) -> bool:
    db = get_db()
    try:
        from datetime import datetime, timezone

        db.table("invite_codes").update({
            "used_by": user_id,
            "used_at": datetime.now(timezone.utc).isoformat(),
        }).eq("code", code.strip().upper()).is_("used_by", "null").execute()
        return True
    except Exception:
        log.exception("access.use_invite_failed", code=code)
        return False


async def create_invite_code(created_by: str, tier: str = "free") -> str:
    db = get_db()
    code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    db.table("invite_codes").insert({
        "code": code,
        "tier": tier,
        "created_by": created_by,
    }).execute()
    return code
