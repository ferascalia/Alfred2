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
