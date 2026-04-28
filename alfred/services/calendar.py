"""Calendar service — ICS generation and invite sending via Resend."""

import base64
import uuid
from datetime import datetime, timedelta

import structlog

log = structlog.get_logger()


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def generate_ics(
    summary: str,
    start_dt: datetime,
    organizer_email: str,
    attendee_email: str,
    duration_minutes: int = 30,
    location: str | None = None,
    description: str | None = None,
    reminder_minutes: int = 15,
) -> str:
    uid = f"{uuid.uuid4()}@alfred"
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    dtstart = start_dt.strftime("%Y%m%dT%H%M%SZ")
    dtend = end_dt.strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Alfred//Calendar//EN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{_ics_escape(summary)}",
        f"ORGANIZER;CN={organizer_email}:mailto:{organizer_email}",
        f"ATTENDEE;CN={attendee_email}:mailto:{attendee_email}",
        "STATUS:CONFIRMED",
    ]
    if location:
        lines.append(f"LOCATION:{_ics_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_ics_escape(description)}")
    lines += [
        "BEGIN:VALARM",
        "TRIGGER:-PT{}M".format(reminder_minutes),
        "ACTION:DISPLAY",
        f"DESCRIPTION:Lembrete: {_ics_escape(summary)}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines)
