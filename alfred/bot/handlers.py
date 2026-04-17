import asyncio
import re
import uuid

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from alfred.db.client import get_db

log = structlog.get_logger()


def _has_date_confirmation(text: str) -> bool:
    """Check if any line starts with 'Confirmando:' (case-insensitive)."""
    return any(
        re.match(r"^\s*confirmando\s*:", line, re.IGNORECASE)
        for line in text.split("\n")
    )


async def _send_response_with_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    response: str,
    telegram_id: int,
    user_name: str,
) -> None:
    """Send response, adding inline confirmation buttons if it contains 'Confirmando:'."""
    if not update.message:
        return

    if _has_date_confirmation(response):
        from alfred.bot.keyboards import date_confirm_keyboard

        confirmation_id = uuid.uuid4().hex[:12]
        if context.user_data is not None:
            context.user_data[f"dateconfirm:{confirmation_id}"] = {
                "telegram_id": telegram_id,
                "user_name": user_name,
                "confirmation_text": response,
            }
        await update.message.reply_text(
            response,
            parse_mode="Markdown",
            reply_markup=date_confirm_keyboard(confirmation_id),
        )
    else:
        await update.message.reply_text(response, parse_mode="Markdown")


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

    chat_id = update.effective_chat.id  # type: ignore[union-attr]

    async def keep_typing() -> None:
        try:
            while True:
                await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    typing_task = context.application.create_task(keep_typing())
    try:
        response = await run_agent(
            telegram_id=tg_user.id,
            user_name=tg_user.full_name,
            message=text,
        )
    finally:
        typing_task.cancel()
        await asyncio.sleep(0)

    await _send_response_with_confirmation(
        update, context, response, tg_user.id, tg_user.full_name,
    )


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        return

    from alfred.agent.loop import run_agent
    from alfred.bot.voice import transcribe_voice

    tg_user = update.effective_user
    chat_id = update.effective_chat.id  # type: ignore[union-attr]

    log.info("voice.received", telegram_id=tg_user.id, duration=getattr(voice, "duration", 0))

    async def keep_typing() -> None:
        try:
            while True:
                await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    typing_task = context.application.create_task(keep_typing())
    try:
        text = await transcribe_voice(voice.file_id)
        log.info("voice.transcribed_text", text=text[:100])

        response = await run_agent(
            telegram_id=tg_user.id,
            user_name=tg_user.full_name,
            message=text,
        )
    except Exception:
        log.exception("voice.error")
        response = "Não consegui processar o áudio. Pode tentar de novo ou escrever?"
    finally:
        typing_task.cancel()
        await asyncio.sleep(0)

    prefix = f"🎙️ _{text}_\n\n" if "text" in dir() else ""
    await _send_response_with_confirmation(
        update, context, prefix + response, tg_user.id, tg_user.full_name,
    )


async def import_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /import — send CSV template with instructions."""
    if not update.effective_user or not update.message:
        return

    import io

    from alfred.services.import_csv import build_template_csv

    csv_bytes = build_template_csv()

    await update.message.reply_document(
        document=io.BytesIO(csv_bytes),
        filename="template_alfred.csv",
        caption=(
            "📥 *Como importar contatos em massa:*\n\n"
            "1\\. Abra o arquivo `template_alfred.csv` no Excel ou Google Sheets\n"
            "2\\. Preencha uma linha por contato\n"
            "3\\. Salve como CSV e envie aqui\n\n"
            "*Colunas disponíveis:*\n"
            "• `display_name` — obrigatório\n"
            "• `company`, `role`, `how_we_met` — texto livre\n"
            "• `cadence_days` — inteiro de 1 a 365 \\(padrão: 15\\)\n"
            "• `relationship_type` — friend \\| professional \\| family \\| other\n"
            "• `tags` — separados por `|` \\(ex: `cliente|vip`\\)\n\n"
            "Máximo de 100 contatos por importação\\."
        ),
        parse_mode="MarkdownV2",
    )


async def import_document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle CSV file upload — validate and show preview with confirm/cancel buttons."""
    if not update.effective_user or not update.message or not update.message.document:
        return

    from alfred.bot.keyboards import import_confirm_keyboard
    from alfred.services.import_csv import build_preview, download_csv, parse_and_validate

    tg_user = update.effective_user
    doc = update.message.document
    chat_id = update.effective_chat.id  # type: ignore[union-attr]

    log.info("import.csv_received", telegram_id=tg_user.id, file_name=doc.file_name)

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        csv_bytes = await download_csv(doc.file_id)
    except Exception:
        log.exception("import.download_failed")
        await update.message.reply_text("Não consegui baixar o arquivo. Tente novamente.")
        return

    rows, errors = parse_and_validate(csv_bytes)

    if errors:
        error_text = "❌ *Erros encontrados no CSV:*\n\n" + "\n".join(f"• {e}" for e in errors)
        error_text += "\n\nCorrija o arquivo e envie novamente."
        await update.message.reply_text(error_text, parse_mode="Markdown")
        return

    preview = build_preview(rows)
    keyboard = import_confirm_keyboard(doc.file_id)
    await update.message.reply_text(preview, parse_mode="Markdown", reply_markup=keyboard)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    data = query.data

    if data.startswith("dateconfirm:"):
        await _handle_date_confirm_callback(query, data, context)
        return

    if data.startswith("import:"):
        await _handle_import_callback(query, data)
        return

    parts = data.split(":", 2)
    if len(parts) < 3:
        return

    action, verb, item_id = parts[0], parts[1], parts[2]

    if action == "nudge":
        await _handle_nudge_callback(query, verb, item_id)


async def _handle_date_confirm_callback(
    query: object, data: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle dateconfirm:yes:{id} and dateconfirm:edit:{id} callbacks."""
    from telegram import CallbackQuery

    from alfred.agent.loop import run_agent

    q: CallbackQuery = query  # type: ignore[assignment]
    parts = data.split(":", 2)
    if len(parts) < 3:
        await q.edit_message_text("Ação inválida.")
        return

    verb, confirmation_id = parts[1], parts[2]
    pending_key = f"dateconfirm:{confirmation_id}"
    pending = (context.user_data or {}).get(pending_key)

    if not pending:
        await q.edit_message_text(
            "⏳ Essa confirmação expirou. Me diga de novo o que quer registrar."
        )
        return

    if verb == "yes":
        # Remove botões e mostra que foi confirmado
        original_text = pending["confirmation_text"]
        await q.edit_message_text(f"{original_text}\n\n✅ _Confirmado_", parse_mode="Markdown")

        # Envia indicador de digitação
        chat_id = q.message.chat_id if q.message else None  # type: ignore[union-attr]
        typing_task = None
        if chat_id:
            async def keep_typing() -> None:
                try:
                    while True:
                        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                        await asyncio.sleep(4)
                except asyncio.CancelledError:
                    pass

            typing_task = context.application.create_task(keep_typing())

        try:
            response = await run_agent(
                telegram_id=pending["telegram_id"],
                user_name=pending["user_name"],
                message="[CONFIRMAÇÃO APROVADA] Confirmo as datas propostas. Execute as ferramentas agora.",
            )
        finally:
            if typing_task:
                typing_task.cancel()
                await asyncio.sleep(0)

        if chat_id:
            await context.bot.send_message(chat_id=chat_id, text=response, parse_mode="Markdown")

        # Limpa dados pendentes
        if context.user_data and pending_key in context.user_data:
            del context.user_data[pending_key]

    elif verb == "edit":
        original_text = pending["confirmation_text"]
        await q.edit_message_text(f"{original_text}\n\n✏️ _Correção solicitada_", parse_mode="Markdown")

        chat_id = q.message.chat_id if q.message else None  # type: ignore[union-attr]
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Sem problemas! Me diga o que quer corrigir — data, pessoa ou ação.",
            )

        # Limpa dados pendentes — próxima mensagem será processada normalmente
        if context.user_data and pending_key in context.user_data:
            del context.user_data[pending_key]
    else:
        await q.edit_message_text("Ação não reconhecida.")


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
        await q.edit_message_text(f"⏰ {result}")
    elif verb == "mute":
        await q.edit_message_text("🔇 Contato silenciado. Não enviarei mais lembretes.")
    else:
        await q.edit_message_text("Ação não reconhecida.")


async def _handle_import_callback(query: object, data: str) -> None:
    """Handle import:confirm:{file_id} and import:cancel callbacks."""
    from telegram import CallbackQuery

    from alfred.db.client import get_db
    from alfred.services.import_csv import bulk_import, download_csv, parse_and_validate

    q: CallbackQuery = query  # type: ignore[assignment]

    if data == "import:cancel":
        await q.edit_message_text("❌ Importação cancelada.")
        return

    # data = "import:confirm:{file_id}"
    parts = data.split(":", 2)
    if len(parts) < 3:
        await q.edit_message_text("Ação inválida.")
        return

    file_id = parts[2]

    if not q.from_user:
        return

    db = get_db()
    user_result = (
        db.table("users").select("id").eq("telegram_id", q.from_user.id).single().execute()
    )
    if not user_result.data:
        await q.edit_message_text("Usuário não encontrado. Use /start primeiro.")
        return

    user_id = user_result.data["id"]

    await q.edit_message_text("⏳ Importando contatos...")

    try:
        csv_bytes = await download_csv(file_id)
    except Exception:
        log.exception("import.confirm_download_failed")
        await q.edit_message_text("Não consegui baixar o arquivo. Envie o CSV novamente com /import.")
        return

    rows, errors = parse_and_validate(csv_bytes)
    if errors:
        await q.edit_message_text("❌ O arquivo parece ter sido modificado. Envie novamente.")
        return

    result = await bulk_import(user_id=user_id, rows=rows)
    created = result["created"]
    skipped: list[str] = result["skipped"]

    s_c = "s" if created != 1 else ""
    msg = f"✅ *{created} contato{s_c} criado{s_c}.*"
    if skipped:
        s_s = "s" if len(skipped) != 1 else ""
        msg += f"\n\n⚠️ {len(skipped)} duplicata{s_s} ignorada{s_s}: {', '.join(skipped)}."

    await q.edit_message_text(msg, parse_mode="Markdown")
