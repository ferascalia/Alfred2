"""Google Calendar service — list, create, update, delete events."""

from datetime import datetime, timedelta

import structlog
from googleapiclient.discovery import build

from alfred.services.oauth import get_google_credentials

log = structlog.get_logger()

NO_INTEGRATION_MSG = (
    "Sua agenda Google não está conectada. Use /connect para vincular."
)


def _build_service(creds):  # type: ignore[no-untyped-def]
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


async def list_events(
    user_id: str,
    start_date: str,
    end_date: str | None = None,
    query: str | None = None,
) -> str:
    creds = await get_google_credentials(user_id)
    if not creds:
        return NO_INTEGRATION_MSG

    start_dt = datetime.fromisoformat(start_date)
    if end_date:
        end_dt = datetime.fromisoformat(end_date)
    else:
        end_dt = start_dt + timedelta(days=7)

    time_min = start_dt.isoformat() + "T00:00:00Z"
    time_max = end_dt.isoformat() + "T23:59:59Z"

    try:
        service = _build_service(creds)
        params: dict = {
            "calendarId": "primary",
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 25,
        }
        if query:
            params["q"] = query

        result = service.events().list(**params).execute()
        events = result.get("items", [])

        if not events:
            return "Nenhum evento encontrado nesse período."

        lines = []
        for ev in events:
            start = ev["start"].get("dateTime", ev["start"].get("date", ""))
            summary = ev.get("summary", "(sem título)")
            location = ev.get("location", "")

            if "T" in start:
                dt = datetime.fromisoformat(start)
                date_str = dt.strftime("%d/%m/%Y %H:%M")
            else:
                dt = datetime.fromisoformat(start)
                date_str = dt.strftime("%d/%m/%Y") + " (dia inteiro)"

            line = f"• {date_str} — {summary}"
            if location:
                line += f" 📍 {location}"
            lines.append(line)

        return "\n".join(lines)

    except Exception as exc:
        log.exception("google_calendar.list_failed", user_id=user_id)
        return f"Erro ao buscar eventos: {exc}"


async def create_event(
    user_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
) -> str:
    creds = await get_google_credentials(user_id)
    if not creds:
        return NO_INTEGRATION_MSG

    body: dict = {
        "summary": title,
        "start": {"dateTime": start_datetime, "timeZone": "America/Sao_Paulo"},
        "end": {"dateTime": end_datetime, "timeZone": "America/Sao_Paulo"},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]

    try:
        service = _build_service(creds)
        event = service.events().insert(
            calendarId="primary",
            body=body,
            sendUpdates="all" if attendees else "none",
        ).execute()

        link = event.get("htmlLink", "")
        log.info("google_calendar.event_created", user_id=user_id, event_id=event["id"])
        return f"Evento criado: {title}\nLink: {link}"

    except Exception as exc:
        log.exception("google_calendar.create_failed", user_id=user_id)
        return f"Erro ao criar evento: {exc}"


async def update_event(
    user_id: str,
    event_id: str,
    fields: dict,
) -> str:
    creds = await get_google_credentials(user_id)
    if not creds:
        return NO_INTEGRATION_MSG

    body: dict = {}
    if "title" in fields:
        body["summary"] = fields["title"]
    if "start_datetime" in fields:
        body["start"] = {"dateTime": fields["start_datetime"], "timeZone": "America/Sao_Paulo"}
    if "end_datetime" in fields:
        body["end"] = {"dateTime": fields["end_datetime"], "timeZone": "America/Sao_Paulo"}
    if "description" in fields:
        body["description"] = fields["description"]
    if "location" in fields:
        body["location"] = fields["location"]
    if "attendees" in fields:
        body["attendees"] = [{"email": e} for e in fields["attendees"]]

    if not body:
        return "Nenhum campo para atualizar."

    try:
        service = _build_service(creds)
        event = service.events().patch(
            calendarId="primary",
            eventId=event_id,
            body=body,
            sendUpdates="all" if "attendees" in body else "none",
        ).execute()

        log.info("google_calendar.event_updated", user_id=user_id, event_id=event_id)
        return f"Evento atualizado: {event.get('summary', event_id)}"

    except Exception as exc:
        log.exception("google_calendar.update_failed", user_id=user_id)
        return f"Erro ao atualizar evento: {exc}"


async def delete_event(user_id: str, event_id: str) -> str:
    creds = await get_google_credentials(user_id)
    if not creds:
        return NO_INTEGRATION_MSG

    try:
        service = _build_service(creds)
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        log.info("google_calendar.event_deleted", user_id=user_id, event_id=event_id)
        return "Evento removido da agenda."

    except Exception as exc:
        log.exception("google_calendar.delete_failed", user_id=user_id)
        return f"Erro ao remover evento: {exc}"
