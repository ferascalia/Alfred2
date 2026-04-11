import structlog
from telegram import Update
from telegram.ext import ContextTypes

from alfred.db.client import get_db

log = structlog.get_logger()


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    tg_user = update.effective_user
    db = get_db()

    # Upsert user
    db.table("users").upsert(
        {
            "telegram_id": tg_user.id,
            "name": tg_user.full_name,
            "timezone": "America/Sao_Paulo",
            "locale": "pt-BR",
        },
        on_conflict="telegram_id",
    ).execute()

    log.info("user.start", telegram_id=tg_user.id, name=tg_user.full_name)

    await update.message.reply_text(
        f"Olá, {tg_user.first_name}! 👋\n\n"
        "Sou o **Alfred**, seu assistente de relacionamentos.\n\n"
        "Estou aqui para ajudar você a manter e aprofundar suas conexões — "
        "amigos, clientes, colegas — sem deixar ninguém cair no esquecimento.\n\n"
        "Pode começar me contando sobre alguém que você encontrou recentemente "
        "ou perguntar o que precisa. Estou ouvindo. 🎩",
        parse_mode="Markdown",
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message or not update.message.text:
        return

    from alfred.agent.loop import run_agent

    tg_user = update.effective_user
    text = update.message.text

    log.info("message.received", telegram_id=tg_user.id, length=len(text))

    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,  # type: ignore[union-attr]
        action="typing",
    )

    response = await run_agent(
        telegram_id=tg_user.id,
        user_name=tg_user.full_name,
        message=text,
    )

    await update.message.reply_text(response, parse_mode="Markdown")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    parts = query.data.split(":")
    if len(parts) < 3:
        return

    action, verb, item_id = parts[0], parts[1], parts[2]

    if action == "nudge":
        await _handle_nudge_callback(query, verb, item_id)


async def _handle_nudge_callback(query: object, verb: str, nudge_id: str) -> None:
    from telegram import CallbackQuery

    from alfred.services.nudges import handle_nudge_action

    q: CallbackQuery = query  # type: ignore[assignment]
    result = await handle_nudge_action(nudge_id=nudge_id, action=verb)

    if verb == "copy":
        await q.edit_message_text(
            f"📋 Mensagem copiada para você:\n\n{result}",
            parse_mode="Markdown",
        )
    elif verb == "done":
        await q.edit_message_text("✅ Interação registrada. Próximo lembrete recalculado.")
    elif verb == "snooze":
        await q.edit_message_text("⏰ Adiado por 7 dias.")
    elif verb == "mute":
        await q.edit_message_text("🔇 Contato silenciado. Não enviarei mais lembretes.")
    else:
        await q.edit_message_text("Ação não reconhecida.")
