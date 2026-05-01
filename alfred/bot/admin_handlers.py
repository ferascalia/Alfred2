"""Admin Telegram commands and /status for all users."""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from alfred.config import settings
from alfred.db.client import get_db
from alfred.services.access import require_access
from alfred.services.limits import build_status_text, get_limits, get_user_tier

log = structlog.get_logger()


def _is_admin(telegram_id: int) -> bool:
    return settings.admin_telegram_id != 0 and telegram_id == settings.admin_telegram_id


@require_access
async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    tg_user = update.effective_user
    db = get_db()
    user_result = db.table("users").select("id").eq("telegram_id", tg_user.id).single().execute()
    if not user_result.data:
        await update.message.reply_text("Usuário não encontrado. Use /start primeiro.")
        return

    user_id = user_result.data["id"]
    text = await build_status_text(user_id)
    await update.message.reply_text(text, parse_mode="Markdown")


async def admin_invite_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not _is_admin(update.effective_user.id):
        return

    from alfred.services.access import create_invite_code

    args = context.args or []
    tier = args[0] if args else "free"
    if tier not in TIER_LIMITS:
        await update.message.reply_text(f"Tier invalido. Use: {', '.join(TIER_LIMITS.keys())}")
        return

    db = get_db()
    user_result = db.table("users").select("id").eq("telegram_id", update.effective_user.id).single().execute()
    admin_id = user_result.data["id"] if user_result.data else None

    code = await create_invite_code(created_by=admin_id, tier=tier)
    await update.message.reply_text(f"Codigo de convite: `{code}`\nTier: {tier}", parse_mode="Markdown")


async def admin_users_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not _is_admin(update.effective_user.id):
        return

    db = get_db()
    result = db.table("users").select("name, tier, status, telegram_id, created_at").order("created_at").execute()
    if not result.data:
        await update.message.reply_text("Nenhum usuario encontrado.")
        return

    lines = [f"*Usuarios ({len(result.data)})*\n"]
    for u in result.data:
        lines.append(f"- {u['name']} | {u['tier']} | {u['status']} | `{u['telegram_id']}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def admin_set_tier_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not _is_admin(update.effective_user.id):
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Uso: /admin\\_set\\_tier <telegram\\_id> <tier>")
        return

    telegram_id = int(args[0])
    tier = args[1]
    if tier not in TIER_LIMITS:
        await update.message.reply_text(f"Tier invalido. Use: {', '.join(TIER_LIMITS.keys())}")
        return

    db = get_db()
    limits = get_limits(tier)
    result = (
        db.table("users")
        .update({
            "tier": tier,
            "monthly_token_budget_usd": limits["budget_usd"],
            "max_contacts": limits["max_contacts"],
            "max_messages_per_day": limits["max_messages_day"],
        })
        .eq("telegram_id", telegram_id)
        .execute()
    )

    if result.data:
        await update.message.reply_text(f"Tier de `{telegram_id}` atualizado para *{tier}*.", parse_mode="Markdown")
    else:
        await update.message.reply_text("Usuario nao encontrado.")
