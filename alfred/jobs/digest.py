"""Weekly digest — lista os contatos mais atrasados para o usuário."""
from datetime import UTC, datetime
from typing import Any

import structlog

from alfred.db.client import get_db

log = structlog.get_logger()


async def process_digest(user_id: str) -> dict[str, Any]:
    db = get_db()

    # Get user telegram_id
    user_result = db.table("users").select("telegram_id, name").eq("id", user_id).single().execute()
    if not user_result.data:
        return {"error": "user not found"}

    telegram_id = user_result.data["telegram_id"]

    # Find top 5 overdue active contacts
    result = (
        db.table("contacts")
        .select("id, display_name, cadence_days, last_interaction_at, next_nudge_at")
        .eq("user_id", user_id)
        .eq("status", "active")
        .or_("next_nudge_at.is.null,next_nudge_at.lte." + datetime.now(UTC).isoformat())
        .order("next_nudge_at", desc=False, nullsfirst=True)
        .limit(5)
        .execute()
    )

    if not result.data:
        log.info("digest.no_overdue_contacts", user_id=user_id)
        return {"status": "skipped", "reason": "no overdue contacts"}

    # Build message
    lines = ["📅 *Resumo semanal — contatos que precisam de atenção:*\n"]
    for c in result.data:
        name = c["display_name"]
        last = c.get("last_interaction_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                days = (datetime.now(UTC) - last_dt).days
                lines.append(f"• {name} — {days} dias sem contato")
            except Exception:
                lines.append(f"• {name} — sem contato recente")
        else:
            lines.append(f"• {name} — nunca contatado")

    lines.append("\nQuer que eu rascunhe uma mensagem para algum deles? É só me dizer o nome.")

    text = "\n".join(lines)

    from telegram import Bot
    from alfred.config import settings

    bot = Bot(token=settings.telegram_bot_token)
    await bot.send_message(
        chat_id=telegram_id,
        text=text,
        parse_mode="Markdown",
    )

    log.info("digest.sent", user_id=user_id, telegram_id=telegram_id, contacts=len(result.data))
    return {"status": "sent", "user_id": user_id, "contacts_count": len(result.data)}
