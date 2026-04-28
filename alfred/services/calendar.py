"""Calendar service — ICS generation and invite sending via Resend."""

import base64
import uuid
from datetime import datetime, timedelta

import resend
import structlog

from alfred.config import settings

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


async def send_calendar_invite(
    to_email: str,
    subject: str,
    body_text: str,
    ics_content: str,
    from_email: str,
) -> str:
    try:
        resend.api_key = settings.resend_api_key
        ics_b64 = base64.b64encode(ics_content.encode("utf-8")).decode("ascii")
        resend.Emails.send({
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "text": body_text,
            "attachments": [
                {
                    "filename": "invite.ics",
                    "content": ics_b64,
                    "content_type": "text/calendar; method=REQUEST",
                }
            ],
        })
        log.info("calendar.invite_sent", to=to_email, subject=subject)
        return f"Convite enviado para {to_email}."
    except Exception as exc:
        log.error("calendar.invite_failed", to=to_email, error=str(exc))
        return f"Erro ao enviar convite para {to_email}: {exc}"
