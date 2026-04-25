"""Conversation history management — load, save, user resolution."""

import structlog
from anthropic.types import MessageParam

from alfred.db.client import get_db

log = structlog.get_logger()


async def get_or_create_user(telegram_id: int, user_name: str) -> str:
    """Return the internal user UUID for a Telegram user."""
    db = get_db()
    result = (
        db.table("users")
        .upsert(
            {
                "telegram_id": telegram_id,
                "name": user_name,
                "timezone": "America/Sao_Paulo",
                "locale": "pt-BR",
            },
            on_conflict="telegram_id",
        )
        .execute()
    )
    return result.data[0]["id"]


async def load_history(user_id: str, limit: int = 20) -> list[MessageParam]:
    """Load recent conversation messages from DB."""
    db = get_db()

    conv_result = (
        db.table("conversations")
        .select("id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not conv_result.data:
        return []

    conv_id = conv_result.data[0]["id"]
    msgs_result = (
        db.table("messages")
        .select("role, content")
        .eq("conversation_id", conv_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    messages: list[MessageParam] = []
    for row in reversed(msgs_result.data):
        messages.append({"role": row["role"], "content": row["content"]})  # type: ignore[typeddict-item]
    return messages


async def save_message(user_id: str, role: str, content: object) -> None:
    db = get_db()

    conv_result = (
        db.table("conversations")
        .select("id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if conv_result.data:
        conv_id = conv_result.data[0]["id"]
        db.table("conversations").update({"last_message_at": "now()"}).eq("id", conv_id).execute()
    else:
        new_conv = db.table("conversations").insert({"user_id": user_id, "telegram_chat_id": 0}).execute()
        conv_id = new_conv.data[0]["id"]

    db.table("messages").insert({
        "conversation_id": conv_id,
        "role": role,
        "content": content,
    }).execute()


async def alert_owner(telegram_id: int, message: str) -> None:
    """Send an urgent alert to the user via Telegram."""
    try:
        from telegram import Bot
        from alfred.config import settings
        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(chat_id=telegram_id, text=message, parse_mode="Markdown")
    except Exception:
        log.exception("alert.failed", telegram_id=telegram_id)


PARTIAL_REPORT_LABELS: dict[str, str] = {
    "create_contact": "Contato criado: {display_name}",
    "create_contact_confirmed": "Contato criado: {display_name}",
    "add_memory": "Memória salva",
    "update_contact": "Contato atualizado",
    "log_interaction": "Interação registrada",
    "set_follow_up": "Follow-up agendado",
    "set_cadence": "Cadência atualizada",
    "archive_contact": "Contato arquivado",
}


def build_partial_report(tool_calls_log: list[tuple[str, dict]]) -> str:
    lines: list[str] = []
    for name, args in tool_calls_log:
        template = PARTIAL_REPORT_LABELS.get(name)
        if template:
            try:
                label = template.format_map(args)
            except KeyError:
                label = template.split(":")[0]
            lines.append(f"✅ {label}")
    return "\n".join(lines) if lines else "Nenhuma ação foi completada."
