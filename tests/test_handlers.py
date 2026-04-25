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
    fake_db.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "u1"}])

    with patch("alfred.bot.handlers.get_db", return_value=fake_db):
        await start_handler(update, context)

    update.message.reply_text.assert_called_once()
    call_args = update.message.reply_text.call_args[0][0]
    assert "Alfred" in call_args
    assert "Feras" in call_args


@pytest.mark.asyncio
async def test_message_handler_calls_agent() -> None:
    from alfred.bot.handlers import message_handler

    update = _make_update("Conheci o João hoje")
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_chat_action = AsyncMock()

    with patch("alfred.agent.orchestrator.run_agent", AsyncMock(return_value="Entendido! Criando contato.")):
        await message_handler(update, context)

    update.message.reply_text.assert_called_once()
    assert "Entendido" in update.message.reply_text.call_args[0][0]


def test_nudge_keyboard_structure() -> None:
    from alfred.bot.keyboards import nudge_keyboard

    kb = nudge_keyboard("nudge-id-123")
    assert len(kb.inline_keyboard) == 2  # 2 rows
    assert len(kb.inline_keyboard[0]) == 2  # 2 buttons per row
    first_button = kb.inline_keyboard[0][0]
    assert "nudge:copy:nudge-id-123" == first_button.callback_data
