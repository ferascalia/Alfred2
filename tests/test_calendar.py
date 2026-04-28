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
