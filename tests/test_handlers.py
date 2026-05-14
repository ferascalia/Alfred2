"""Tests for bot command parsing and callback handling."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_update(text: str, user_id: int = 123, first_name: str = "Feras") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.full_name = first_name
    user.first_name = first_name

    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()

    update = MagicMock()
    update.effective_user = user
    update.message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = 999

    return update


@pytest.mark.asyncio
async def test_start_handler_sends_welcome() -> None:
    from alfred.bot.handlers import start_handler

    update = _make_update("/start")
    context = MagicMock()

    fake_db = MagicMock()
    fake_db.table.return_value.upsert.return_value.execute.return_value = MagicMock(
        data=[{"id": "u1", "tier": "free"}],
    )

    with patch("alfred.bot.handlers.get_db", return_value=fake_db), \
         patch("alfred.services.access.check_access", AsyncMock(return_value=True)), \
         patch("alfred.bot.handlers.asyncio.sleep", new_callable=AsyncMock):
        await start_handler(update, context)

    assert update.message.reply_text.call_count == 3
    first_call = update.message.reply_text.call_args_list[0][0][0]
    assert "Alfred" in first_call
    assert "Feras" in first_call
    second_call = update.message.reply_text.call_args_list[1][0][0]
    assert "Grátis" in second_call
    assert "25 contatos" in second_call
    third_call = update.message.reply_text.call_args_list[2]
    assert third_call.kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_help_handler_sends_reference() -> None:
    from alfred.bot.handlers import help_handler

    update = _make_update("/help")
    context = MagicMock()

    with patch("alfred.services.access.check_access", AsyncMock(return_value=True)):
        await help_handler(update, context)

    update.message.reply_text.assert_called_once()
    call_args = update.message.reply_text.call_args[0][0]
    assert "Referência rápida" in call_args
    assert "Cadastrar contato" in call_args


@pytest.mark.asyncio
async def test_message_handler_calls_agent() -> None:
    from alfred.bot.handlers import message_handler

    update = _make_update("Conheci o João hoje")
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_chat_action = AsyncMock()

    with patch("alfred.services.access.check_access", AsyncMock(return_value=True)), \
         patch("alfred.agent.orchestrator.run_agent", AsyncMock(return_value="Entendido! Criando contato.")):
        await message_handler(update, context)

    update.message.reply_text.assert_called_once()
    assert "Entendido" in update.message.reply_text.call_args[0][0]


def test_has_scheduling_choice_detects_marker() -> None:
    from alfred.bot.handlers import _has_scheduling_choice

    assert _has_scheduling_choice(
        "Escolha como agendar:\n• Hugo Oliveira — 14/05/2026 às 17:00"
    )


def test_has_scheduling_choice_case_insensitive() -> None:
    from alfred.bot.handlers import _has_scheduling_choice

    assert _has_scheduling_choice("ESCOLHA COMO AGENDAR:\n• Hugo — 14/05/2026")
    assert _has_scheduling_choice("escolha como agendar:\n• Hugo — 14/05/2026")


def test_has_scheduling_choice_rejects_mid_text() -> None:
    from alfred.bot.handlers import _has_scheduling_choice

    assert not _has_scheduling_choice(
        "Feito! Escolha como agendar: algo"
    )


def test_has_scheduling_choice_rejects_empty() -> None:
    from alfred.bot.handlers import _has_scheduling_choice

    assert not _has_scheduling_choice("")


def test_has_reminder_followup_detects_marker() -> None:
    from alfred.bot.handlers import _has_reminder_followup

    assert _has_reminder_followup(
        "Evento criado na agenda.\n\nLembrete no Telegram?"
    )


def test_has_reminder_followup_case_insensitive() -> None:
    from alfred.bot.handlers import _has_reminder_followup

    assert _has_reminder_followup("LEMBRETE NO TELEGRAM?")
    assert _has_reminder_followup("lembrete no telegram?")


def test_has_reminder_followup_rejects_unrelated() -> None:
    from alfred.bot.handlers import _has_reminder_followup

    assert not _has_reminder_followup("Confirmando: Hugo — 14/05/2026")


@pytest.mark.asyncio
async def test_callback_handler_routes_schedulechoice() -> None:
    """Verify callback_handler dispatches schedulechoice: callbacks."""
    from alfred.bot.handlers import callback_handler

    query = MagicMock()
    query.answer = AsyncMock()
    query.data = "does-not-matter"
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.chat_id = 999
    query.from_user = MagicMock()
    query.from_user.id = 123

    update = MagicMock()
    update.callback_query = query

    context = MagicMock()
    context.user_data = {}
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_chat_action = AsyncMock()
    mock_task = MagicMock()
    mock_task.cancel = MagicMock()
    context.application = MagicMock()
    context.application.create_task = MagicMock(return_value=mock_task)

    from alfred.bot.signing import sign_callback
    signed = sign_callback("schedulechoice:calendar:testid123")
    query.data = signed

    context.user_data["schedulechoice:testid123"] = {
        "telegram_id": 123,
        "user_name": "Test",
        "confirmation_text": "Escolha como agendar:\n• Hugo — 14/05/2026 às 17:00",
    }

    with patch("alfred.services.access.check_access", AsyncMock(return_value=True)), \
         patch("alfred.bot.handlers.asyncio.sleep", new_callable=AsyncMock), \
         patch("alfred.agent.orchestrator.run_agent", AsyncMock(return_value="Agendando:\n• Hugo — 14/05/2026 às 17:00")):
        await callback_handler(update, context)

    query.edit_message_text.assert_called_once()
    context.bot.send_message.assert_called_once()


def test_nudge_keyboard_structure() -> None:
    from alfred.bot.keyboards import nudge_keyboard
    from alfred.bot.signing import verify_callback

    kb = nudge_keyboard("nudge-id-123")
    assert len(kb.inline_keyboard) == 2  # 2 rows
    assert len(kb.inline_keyboard[0]) == 2  # 2 buttons per row
    first_button = kb.inline_keyboard[0][0]
    assert verify_callback(first_button.callback_data) == "nudge:copy:nudge-id-123"
