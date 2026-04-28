"""Tests for calendar service — ICS generation and invite sending."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Task 3: generate_ics
# ---------------------------------------------------------------------------

def test_generate_ics_basic():
    from alfred.services.calendar import generate_ics

    ics = generate_ics(
        summary="Almoço com Marina",
        start_dt=datetime(2026, 5, 1, 12, 30),
        organizer_email="user@example.com",
        attendee_email="marina@example.com",
    )
    assert "BEGIN:VCALENDAR" in ics
    assert "BEGIN:VEVENT" in ics
    assert "SUMMARY:Almoço com Marina" in ics
    assert "DTSTART:20260501T123000Z" in ics
    assert "DTEND:20260501T130000Z" in ics  # default 30min
    assert "ATTENDEE;CN=marina@example.com:mailto:marina@example.com" in ics
    assert "ORGANIZER;CN=user@example.com:mailto:user@example.com" in ics
    assert "BEGIN:VALARM" in ics
    assert "END:VCALENDAR" in ics


def test_generate_ics_with_location():
    from alfred.services.calendar import generate_ics

    ics = generate_ics(
        summary="Reunião",
        start_dt=datetime(2026, 5, 1, 14, 0),
        organizer_email="user@example.com",
        attendee_email="contact@example.com",
        location="Restaurante Fasano, Jardins",
    )
    assert "LOCATION:Restaurante Fasano\\, Jardins" in ics


def test_generate_ics_custom_duration():
    from alfred.services.calendar import generate_ics

    ics = generate_ics(
        summary="Workshop",
        start_dt=datetime(2026, 5, 1, 9, 0),
        organizer_email="user@example.com",
        attendee_email="contact@example.com",
        duration_minutes=60,
    )
    assert "DTEND:20260501T100000Z" in ics


def test_generate_ics_with_description():
    from alfred.services.calendar import generate_ics

    ics = generate_ics(
        summary="Café",
        start_dt=datetime(2026, 5, 1, 10, 0),
        organizer_email="user@example.com",
        attendee_email="contact@example.com",
        description="Discutir parceria de Q3",
    )
    assert "DESCRIPTION:Discutir parceria de Q3" in ics


# ---------------------------------------------------------------------------
# Task 4: send_calendar_invite
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_calendar_invite_success():
    from alfred.services.calendar import send_calendar_invite

    mock_resend = MagicMock()
    mock_resend.Emails.send.return_value = {"id": "email_123"}

    with patch("alfred.services.calendar.resend", mock_resend):
        result = await send_calendar_invite(
            to_email="marina@example.com",
            subject="Almoço com Marina",
            body_text="Convite de calendário para almoço.",
            ics_content="BEGIN:VCALENDAR\r\nEND:VCALENDAR",
            from_email="alfred@example.com",
        )
    assert "Convite enviado" in result
    mock_resend.Emails.send.assert_called_once()
    call_kwargs = mock_resend.Emails.send.call_args[0][0]
    assert call_kwargs["to"] == ["marina@example.com"]
    assert len(call_kwargs["attachments"]) == 1
    assert call_kwargs["attachments"][0]["filename"] == "invite.ics"


@pytest.mark.asyncio
async def test_send_calendar_invite_failure():
    from alfred.services.calendar import send_calendar_invite

    mock_resend = MagicMock()
    mock_resend.Emails.send.side_effect = Exception("API error")

    with patch("alfred.services.calendar.resend", mock_resend):
        result = await send_calendar_invite(
            to_email="marina@example.com",
            subject="Almoço",
            body_text="Convite.",
            ics_content="BEGIN:VCALENDAR\r\nEND:VCALENDAR",
            from_email="alfred@example.com",
        )
    assert "Erro ao enviar" in result


# ---------------------------------------------------------------------------
# Task 5: send_calendar_invite_tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_calendar_invite_tool_success():
    from alfred.services.calendar import send_calendar_invite_tool

    fake_contact = {"display_name": "Marina", "email": None, "user_id": "u1"}
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=fake_contact)

    mock_resend = MagicMock()
    mock_resend.Emails.send.return_value = {"id": "email_123"}

    with (
        patch("alfred.services.calendar.get_db", return_value=fake_db),
        patch("alfred.services.calendar.resend", mock_resend),
        patch("alfred.services.calendar.settings") as mock_settings,
    ):
        mock_settings.calendar_sender_email = "alfred@example.com"
        mock_settings.resend_api_key = "re_test"
        result = await send_calendar_invite_tool(
            user_id="u1",
            contact_id="c1",
            contact_email="marina@example.com",
            title="Almoço com Marina",
            start_datetime="2026-05-01T12:30:00",
        )
    assert "Convite enviado" in result


@pytest.mark.asyncio
async def test_send_calendar_invite_tool_contact_not_found():
    from alfred.services.calendar import send_calendar_invite_tool

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)

    with patch("alfred.services.calendar.get_db", return_value=fake_db):
        result = await send_calendar_invite_tool(
            user_id="u1",
            contact_id="c1",
            contact_email="marina@example.com",
            title="Almoço",
            start_datetime="2026-05-01T12:30:00",
        )
    assert "não encontrado" in result


@pytest.mark.asyncio
async def test_dispatch_send_calendar_invite():
    from alfred.agent.tools.dispatch import dispatch_tool

    with patch(
        "alfred.services.calendar.send_calendar_invite_tool",
        AsyncMock(return_value="Convite enviado para marina@example.com."),
    ):
        result = await dispatch_tool(
            "send_calendar_invite",
            {
                "contact_id": "c1",
                "contact_email": "marina@example.com",
                "title": "Almoço",
                "start_datetime": "2026-05-01T12:30:00",
            },
            user_id="u1",
        )
    assert "Convite enviado" in result


# ─── Integration tests ──────────────────────────────────────────────


def test_send_calendar_invite_schema_valid():
    from alfred.agent.tools.schemas import SEND_CALENDAR_INVITE_SCHEMA

    assert SEND_CALENDAR_INVITE_SCHEMA["name"] == "send_calendar_invite"
    assert "contact_id" in SEND_CALENDAR_INVITE_SCHEMA["input_schema"]["required"]
    assert "start_datetime" in SEND_CALENDAR_INVITE_SCHEMA["input_schema"]["required"]


def test_calendar_tools_in_all_schemas():
    from alfred.agent.tools.schemas import ALL_TOOL_SCHEMAS

    names = [t["name"] for t in ALL_TOOL_SCHEMAS]
    assert "send_calendar_invite" in names


def test_activity_agent_has_calendar_tools():
    from alfred.agent.agents.activity import ActivityAgent

    agent = ActivityAgent()
    tool_names = [t["name"] for t in agent.get_tools()]
    assert "send_calendar_invite" in tool_names
    assert "update_contact" in tool_names


def test_activity_agent_prompt_has_scheduling():
    from alfred.agent.agents.activity import ActivityAgent
    from alfred.agent.context import AgentContext

    agent = ActivityAgent()
    ctx = AgentContext(
        user_id="u1",
        telegram_id=123,
        user_name="Test",
        message="test",
        current_date="2026-04-28",
        is_confirmation=False,
    )
    prompt = agent.build_prompt(ctx)
    assert "send_calendar_invite" in prompt
    assert "Agendamento de eventos" in prompt
