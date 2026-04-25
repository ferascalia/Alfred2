import asyncio
import re
import uuid

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from alfred.db.client import get_db

log = structlog.get_logger()

_import_states: dict[str, dict] = {}


def _get_import_state(user_id: str) -> dict | None:
    return _import_states.get(user_id)


def _set_import_state(user_id: str, state: dict) -> None:
    _import_states[user_id] = state


def _clear_import_state(user_id: str) -> None:
    _import_states.pop(user_id, None)


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


def _use_multi_agent(telegram_id: int) -> bool:
    """Check if this user should use multi-agent orchestrator."""
    from alfred.config import settings
    if settings.use_multi_agent:
        return True
    if settings.multi_agent_test_ids:
        test_ids = {int(x.strip()) for x in settings.multi_agent_test_ids.split(",") if x.strip()}
        return telegram_id in test_ids
    return False


def _get_run_agent(telegram_id: int):
    """Return the appropriate run_agent based on feature flag and user."""
    if _use_multi_agent(telegram_id):
        from alfred.agent.orchestrator import run_agent
    else:
        from alfred.agent.loop import run_agent
    return run_agent


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message or not update.message.text:
        return

    tg_user = update.effective_user
    text = update.message.text
    run_agent = _get_run_agent(tg_user.id)

    log.info("message.received", telegram_id=tg_user.id, length=len(text),
             multi_agent=_use_multi_agent(tg_user.id))

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
    except Exception:
        log.exception("message_handler.agent_error", telegram_id=tg_user.id)
        response = "Desculpe, tive um problema técnico. Pode tentar de novo? 🙏"
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

    from alfred.bot.voice import transcribe_voice

    tg_user = update.effective_user
    run_agent = _get_run_agent(tg_user.id)
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

    from alfred.services.import_contacts import build_template_csv

    csv_bytes = build_template_csv()
    buf = io.BytesIO(csv_bytes)
    buf.name = "template_alfred.csv"

    await update.message.reply_document(
        document=buf,
        filename="template_alfred.csv",
        caption=(
            "📥 *Como importar contatos em massa:*\n\n"
            "1\\. Abra o arquivo `template_alfred.csv` no Excel ou Google Sheets\n"
            "2\\. Preencha uma linha por contato\n"
            "3\\. Salve como CSV ou envie a planilha Excel \\(\\.xlsx\\) direto\n\n"
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
    """Handle CSV/XLSX file upload — validate, detect duplicates, show grouped preview."""
    if not update.effective_user or not update.message or not update.message.document:
        return
    from alfred.bot.keyboards import import_preview_keyboard
    from alfred.services.import_contacts import (
        build_grouped_preview,
        check_duplicates,
        download_file,
        parse_and_validate,
        parse_xlsx,
    )

    tg_user = update.effective_user
    doc = update.message.document
    file_name = (doc.file_name or "").lower()

    log.info("import.file_received", telegram_id=tg_user.id, file_name=file_name)

    try:
        file_bytes = await download_file(doc.file_id)
    except Exception:
        log.exception("import.download_failed")
        await update.message.reply_text("Não consegui baixar o arquivo. Tente novamente.")
        return

    if file_name.endswith(".xlsx"):
        rows, errors = parse_xlsx(file_bytes)
    else:
        rows, errors = parse_and_validate(file_bytes)

    if errors:
        error_text = "❌ *Erros encontrados no arquivo:*\n\n" + "\n".join(f"• {e}" for e in errors)
        await update.message.reply_text(error_text, parse_mode="Markdown")
        return

    db = get_db()
    user_result = db.table("users").select("id").eq("telegram_id", tg_user.id).single().execute()
    if not user_result.data:
        await update.message.reply_text("Use /start primeiro para se registrar.")
        return
    user_id = user_result.data["id"]

    clean, duplicates = await check_duplicates(user_id=user_id, rows=rows)

    _set_import_state(user_id, {
        "clean_rows": clean,
        "duplicates": duplicates,
        "decisions": {},
        "current_review_index": 0,
    })

    preview = build_grouped_preview(clean, duplicates)
    has_duplicates = len(duplicates) > 0
    keyboard = import_preview_keyboard(user_id, has_duplicates=has_duplicates)

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

    run_agent = _get_run_agent(pending["telegram_id"])

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
        await q.edit_message_text("📋 Mensagem copiada abaixo ⬇️")
        await q.message.reply_text(
            f"```\n{result}\n```",
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
    """Handle all import callbacks: preview actions and duplicate review decisions."""
    from telegram import CallbackQuery

    from alfred.bot.keyboards import duplicate_review_keyboard
    from alfred.services.import_contacts import (
        build_duplicate_comparison,
        build_import_report,
        execute_import,
    )

    q: CallbackQuery = query  # type: ignore[assignment]

    if data == "import:cancel":
        await q.edit_message_text("❌ Importação cancelada.")
        return

    parts = data.split(":")
    if len(parts) < 3:
        await q.edit_message_text("Ação inválida.")
        return

    action = parts[1]
    user_id = parts[2]

    state = _get_import_state(user_id)
    if not state:
        await q.edit_message_text("Sessão de importação expirada. Envie o arquivo novamente.")
        return

    clean_rows = state["clean_rows"]
    duplicates = state["duplicates"]
    decisions = state["decisions"]

    def _decisions_by_name(index_decisions: dict) -> dict:
        """Convert {int_index: decision} to {display_name: decision} for execute_import."""
        result: dict = {}
        for idx, decision in index_decisions.items():
            try:
                dup = duplicates[int(idx)]
                name = dup["csv_row"]["display_name"]
                result[name] = decision
            except (IndexError, KeyError):
                pass
        return result

    if action == "confirm_all":
        await q.edit_message_text("⏳ Importando contatos...")
        result = await execute_import(user_id, clean_rows, [], {})
        _clear_import_state(user_id)
        report = build_import_report(result)
        await q.edit_message_text(report, parse_mode="MarkdownV2")

    elif action == "clean_and_skip":
        await q.edit_message_text("⏳ Importando contatos...")
        all_skip = {i: "skip" for i in range(len(duplicates))}
        result = await execute_import(user_id, clean_rows, duplicates, _decisions_by_name(all_skip))
        _clear_import_state(user_id)
        report = build_import_report(result)
        await q.edit_message_text(report, parse_mode="MarkdownV2")

    elif action == "import_all":
        await q.edit_message_text("⏳ Importando contatos...")
        all_new = {i: "import_new" for i in range(len(duplicates))}
        result = await execute_import(user_id, clean_rows, duplicates, _decisions_by_name(all_new))
        _clear_import_state(user_id)
        report = build_import_report(result)
        await q.edit_message_text(report, parse_mode="MarkdownV2")

    elif action == "review":
        state["current_review_index"] = 0
        dup = duplicates[0]
        comparison = build_duplicate_comparison(dup, 0, len(duplicates))
        keyboard = duplicate_review_keyboard(user_id, 0)
        await q.edit_message_text(comparison, parse_mode="Markdown", reply_markup=keyboard)

    elif action.startswith("dup_"):
        if len(parts) < 4:
            return
        dup_action = action.replace("dup_", "")
        dup_index = int(parts[3])

        action_map = {"skip": "skip", "new": "import_new", "merge": "merge", "replace": "replace"}
        decisions[dup_index] = action_map.get(dup_action, "skip")

        next_index = dup_index + 1
        if next_index < len(duplicates):
            state["current_review_index"] = next_index
            dup = duplicates[next_index]
            comparison = build_duplicate_comparison(dup, next_index, len(duplicates))
            keyboard = duplicate_review_keyboard(user_id, next_index)
            await q.edit_message_text(comparison, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await q.edit_message_text("⏳ Importando contatos...")
            result = await execute_import(user_id, clean_rows, duplicates, _decisions_by_name(decisions))
            _clear_import_state(user_id)
            report = build_import_report(result)
            await q.edit_message_text(report, parse_mode="MarkdownV2")
