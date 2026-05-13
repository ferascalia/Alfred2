"""Tests for Google Calendar integration — OAuth, calendar service, tools, dispatch."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# OAuth service tests
# ---------------------------------------------------------------------------

def test_oauth_sign_state():
    from alfred.bot.oauth_routes import _sign_state, _verify_state

    signed = _sign_state(12345)
    assert "." in signed
    assert _verify_state(signed) == 12345


def test_oauth_verify_state_invalid():
    from alfred.bot.oauth_routes import _verify_state

    assert _verify_state("invalid") is None
    assert _verify_state("12345.badhmac") is None


@pytest.mark.asyncio
async def test_store_and_get_tokens():
    from google.oauth2.credentials import Credentials

    from alfred.services.oauth import get_google_credentials, store_tokens

    fake_creds = MagicMock(spec=Credentials)
    fake_creds.token = "access_token_123"
    fake_creds.refresh_token = "refresh_token_456"
    fake_creds.expiry = datetime.now(UTC) + timedelta(hours=1)
    fake_creds.scopes = ["https://www.googleapis.com/auth/calendar"]

    fake_db = MagicMock()
    fake_db.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{}])

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        await store_tokens("user-1", "google", fake_creds)

    fake_db.table.assert_called_with("user_integrations")
    upsert_call = fake_db.table.return_value.upsert.call_args[0][0]
    assert upsert_call["user_id"] == "user-1"
    assert upsert_call["access_token"] == "access_token_123"
    assert upsert_call["refresh_token"] == "refresh_token_456"
    assert upsert_call["status"] == "active"


@pytest.mark.asyncio
async def test_get_google_credentials_not_found():
    from alfred.services.oauth import get_google_credentials

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        result = await get_google_credentials("user-1")

    assert result is None


@pytest.mark.asyncio
async def test_get_google_credentials_revoked():
    from alfred.services.oauth import get_google_credentials

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"access_token": "tok", "refresh_token": "ref", "token_expires_at": None, "scopes": [], "status": "revoked"}
    )

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        result = await get_google_credentials("user-1")

    assert result is None


@pytest.mark.asyncio
async def test_has_google_integration_true():
    from alfred.services.oauth import has_google_integration

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"status": "active"}]
    )

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        assert await has_google_integration("user-1") is True


@pytest.mark.asyncio
async def test_has_google_integration_false():
    from alfred.services.oauth import has_google_integration

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[]
    )

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        assert await has_google_integration("user-1") is False


@pytest.mark.asyncio
async def test_revoke_google():
    from alfred.services.oauth import revoke_google

    fake_db = MagicMock()
    fake_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        result = await revoke_google("user-1")

    assert result is True
    update_call = fake_db.table.return_value.update.call_args[0][0]
    assert update_call["status"] == "revoked"


# ---------------------------------------------------------------------------
# Google Calendar service tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_events_no_integration():
    from alfred.services.google_calendar import list_events

    with patch("alfred.services.google_calendar.get_google_credentials", AsyncMock(return_value=None)):
        result = await list_events("user-1", "2026-05-15")

    assert "/connect" in result


@pytest.mark.asyncio
async def test_list_events_success():
    from alfred.services.google_calendar import list_events

    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "summary": "Reunião com João",
                "start": {"dateTime": "2026-05-15T14:00:00-03:00"},
                "location": "Google Meet",
            },
            {
                "summary": "Almoço",
                "start": {"date": "2026-05-16"},
            },
        ]
    }

    with (
        patch("alfred.services.google_calendar.get_google_credentials", AsyncMock(return_value=fake_creds)),
        patch("alfred.services.google_calendar._build_service", return_value=fake_service),
    ):
        result = await list_events("user-1", "2026-05-15", "2026-05-16")

    assert "Reunião com João" in result
    assert "Google Meet" in result
    assert "Almoço" in result
    assert "dia inteiro" in result


@pytest.mark.asyncio
async def test_list_events_empty():
    from alfred.services.google_calendar import list_events

    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.events.return_value.list.return_value.execute.return_value = {"items": []}

    with (
        patch("alfred.services.google_calendar.get_google_credentials", AsyncMock(return_value=fake_creds)),
        patch("alfred.services.google_calendar._build_service", return_value=fake_service),
    ):
        result = await list_events("user-1", "2026-05-15")

    assert "Nenhum evento" in result


@pytest.mark.asyncio
async def test_create_event_success():
    from alfred.services.google_calendar import create_event

    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.events.return_value.insert.return_value.execute.return_value = {
        "id": "event123",
        "htmlLink": "https://calendar.google.com/event/event123",
    }

    with (
        patch("alfred.services.google_calendar.get_google_credentials", AsyncMock(return_value=fake_creds)),
        patch("alfred.services.google_calendar._build_service", return_value=fake_service),
    ):
        result = await create_event(
            "user-1",
            title="Reunião com João",
            start_datetime="2026-05-15T14:00:00",
            end_datetime="2026-05-15T15:00:00",
            location="Google Meet",
        )

    assert "Evento criado" in result
    assert "Reunião com João" in result
    insert_body = fake_service.events.return_value.insert.call_args[1]["body"]
    assert insert_body["summary"] == "Reunião com João"
    assert insert_body["location"] == "Google Meet"


@pytest.mark.asyncio
async def test_create_event_no_integration():
    from alfred.services.google_calendar import create_event

    with patch("alfred.services.google_calendar.get_google_credentials", AsyncMock(return_value=None)):
        result = await create_event(
            "user-1",
            title="Teste",
            start_datetime="2026-05-15T14:00:00",
            end_datetime="2026-05-15T15:00:00",
        )

    assert "/connect" in result


@pytest.mark.asyncio
async def test_update_event_success():
    from alfred.services.google_calendar import update_event

    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.events.return_value.patch.return_value.execute.return_value = {
        "id": "event123",
        "summary": "Reunião atualizada",
    }

    with (
        patch("alfred.services.google_calendar.get_google_credentials", AsyncMock(return_value=fake_creds)),
        patch("alfred.services.google_calendar._build_service", return_value=fake_service),
    ):
        result = await update_event(
            "user-1",
            event_id="event123",
            fields={"title": "Reunião atualizada", "location": "Zoom"},
        )

    assert "Evento atualizado" in result


@pytest.mark.asyncio
async def test_update_event_empty_fields():
    from alfred.services.google_calendar import update_event

    fake_creds = MagicMock()

    with patch("alfred.services.google_calendar.get_google_credentials", AsyncMock(return_value=fake_creds)):
        result = await update_event("user-1", event_id="event123", fields={})

    assert "Nenhum campo" in result


@pytest.mark.asyncio
async def test_delete_event_success():
    from alfred.services.google_calendar import delete_event

    fake_creds = MagicMock()
    fake_service = MagicMock()
    fake_service.events.return_value.delete.return_value.execute.return_value = None

    with (
        patch("alfred.services.google_calendar.get_google_credentials", AsyncMock(return_value=fake_creds)),
        patch("alfred.services.google_calendar._build_service", return_value=fake_service),
    ):
        result = await delete_event("user-1", "event123")

    assert "removido" in result


# ---------------------------------------------------------------------------
# Tool dispatch tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_list_calendar_events():
    from alfred.agent.tools.dispatch import dispatch_tool

    with patch(
        "alfred.services.google_calendar.list_events",
        AsyncMock(return_value="• 15/05/2026 14:00 — Reunião com João"),
    ):
        result = await dispatch_tool(
            "list_calendar_events",
            {"start_date": "2026-05-15"},
            user_id="u1",
        )
    assert "Reunião com João" in result


@pytest.mark.asyncio
async def test_dispatch_create_calendar_event():
    from alfred.agent.tools.dispatch import dispatch_tool

    with patch(
        "alfred.services.google_calendar.create_event",
        AsyncMock(return_value="Evento criado: Reunião com João"),
    ):
        result = await dispatch_tool(
            "create_calendar_event",
            {
                "title": "Reunião com João",
                "start_datetime": "2026-05-15T14:00:00",
                "end_datetime": "2026-05-15T15:00:00",
            },
            user_id="u1",
        )
    assert "Evento criado" in result


@pytest.mark.asyncio
async def test_dispatch_update_calendar_event():
    from alfred.agent.tools.dispatch import dispatch_tool

    with patch(
        "alfred.services.google_calendar.update_event",
        AsyncMock(return_value="Evento atualizado: Reunião"),
    ):
        result = await dispatch_tool(
            "update_calendar_event",
            {"event_id": "ev1", "fields": {"title": "Reunião atualizada"}},
            user_id="u1",
        )
    assert "Evento atualizado" in result


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

def test_google_calendar_schemas_valid():
    from alfred.agent.tools.schemas import (
        CREATE_CALENDAR_EVENT_SCHEMA,
        LIST_CALENDAR_EVENTS_SCHEMA,
        UPDATE_CALENDAR_EVENT_SCHEMA,
    )

    assert LIST_CALENDAR_EVENTS_SCHEMA["name"] == "list_calendar_events"
    assert "start_date" in LIST_CALENDAR_EVENTS_SCHEMA["input_schema"]["required"]

    assert CREATE_CALENDAR_EVENT_SCHEMA["name"] == "create_calendar_event"
    assert "title" in CREATE_CALENDAR_EVENT_SCHEMA["input_schema"]["required"]
    assert "start_datetime" in CREATE_CALENDAR_EVENT_SCHEMA["input_schema"]["required"]

    assert UPDATE_CALENDAR_EVENT_SCHEMA["name"] == "update_calendar_event"
    assert "event_id" in UPDATE_CALENDAR_EVENT_SCHEMA["input_schema"]["required"]


def test_google_calendar_tools_in_all_schemas():
    from alfred.agent.tools.schemas import ALL_TOOL_SCHEMAS

    names = [t["name"] for t in ALL_TOOL_SCHEMAS]
    assert "list_calendar_events" in names
    assert "create_calendar_event" in names
    assert "update_calendar_event" in names


def test_activity_agent_has_google_calendar_tools():
    from alfred.agent.agents.activity import ActivityAgent

    agent = ActivityAgent()
    tool_names = [t["name"] for t in agent.get_tools()]
    assert "list_calendar_events" in tool_names
    assert "create_calendar_event" in tool_names
    assert "update_calendar_event" in tool_names


def test_query_agent_has_list_calendar_events():
    from alfred.agent.agents.query import QueryAgent

    agent = QueryAgent()
    tool_names = [t["name"] for t in agent.get_tools()]
    assert "list_calendar_events" in tool_names


def test_activity_agent_prompt_has_google_calendar():
    from alfred.agent.agents.activity import ActivityAgent
    from alfred.agent.context import AgentContext

    agent = ActivityAgent()
    ctx = AgentContext(
        user_id="u1",
        telegram_id=123,
        user_name="Test",
        message="test",
        current_date="2026-05-13",
        is_confirmation=False,
    )
    prompt = agent.build_prompt(ctx)
    assert "Google Calendar" in prompt
    assert "list_calendar_events" in prompt
    assert "create_calendar_event" in prompt
    assert "Agendando:" in prompt


# ---------------------------------------------------------------------------
# Confirmation flow tests
# ---------------------------------------------------------------------------

def test_has_calendar_confirmation():
    from alfred.bot.handlers import _has_calendar_confirmation

    assert _has_calendar_confirmation("Agendando:\n• Reunião com João")
    assert _has_calendar_confirmation("  agendando: algo")
    assert not _has_calendar_confirmation("Confirmando: algo")
    assert not _has_calendar_confirmation("Algum texto normal")


def test_calendar_confirm_keyboard():
    from alfred.bot.keyboards import calendar_confirm_keyboard

    kb = calendar_confirm_keyboard("abc123")
    buttons = kb.inline_keyboard[0]
    assert len(buttons) == 2
    assert "Agendar" in buttons[0].text
    assert "Corrigir" in buttons[1].text
    assert "calendarconfirm:yes:abc123" in buttons[0].callback_data
    assert "calendarconfirm:edit:abc123" in buttons[1].callback_data
