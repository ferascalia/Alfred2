# alfred/integrations/google_calendar.py
"""Google Calendar integration — OAuth + Calendar API adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from alfred.config import settings
from alfred.integrations.base import IntegrationProvider, ProviderInfo
from alfred.services.oauth import get_tokens, mark_expired, store_tokens

log = structlog.get_logger()

SLUG = "google_calendar"

_SCOPES = ["https://www.googleapis.com/auth/calendar"]

_CLIENT_CONFIG = {
    "web": {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uris": [settings.google_redirect_uri],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

_NO_INTEGRATION_MSG = "Sua agenda não está conectada. Use /connect para vincular."

# PKCE verifiers — keyed by state token.
# In-process only; Railway single-instance makes this acceptable for now.
_pending_verifiers: dict[str, str | None] = {}


def _build_google_service(creds: Credentials):
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _tokens_to_credentials(tokens: dict) -> Credentials:
    expiry_raw = tokens.get("token_expires_at")
    expiry = datetime.fromisoformat(expiry_raw) if expiry_raw else None
    return Credentials(
        token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token") or None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=tokens.get("scopes") or _SCOPES,
        expiry=expiry.replace(tzinfo=None) if expiry else None,
    )


async def _get_valid_credentials(user_id: str) -> Credentials | None:
    tokens = await get_tokens(user_id, SLUG)
    if not tokens:
        return None

    creds = _tokens_to_credentials(tokens)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleAuthRequest())
            await store_tokens(user_id, SLUG, {
                "access_token": creds.token,
                "refresh_token": creds.refresh_token,
                "expires_at": creds.expiry.replace(tzinfo=UTC).isoformat() if creds.expiry else "",
                "scopes": list(creds.scopes or _SCOPES),
            })
            log.info("google_calendar.token_refreshed", user_id=user_id)
        except Exception:
            log.exception("google_calendar.refresh_failed", user_id=user_id)
            await mark_expired(user_id, SLUG)
            return None

    return creds


class GoogleCalendarProvider(IntegrationProvider):

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            slug=SLUG,
            display_name="Google Calendar",
            emoji="📅",
            description="Ver e criar eventos na sua agenda Google",
            category="calendar",
            scopes_summary="Acesso completo à agenda",
        )

    def build_auth_url(self, state: str) -> str:
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            _CLIENT_CONFIG, scopes=_SCOPES, redirect_uri=settings.google_redirect_uri,
        )
        url, _ = flow.authorization_url(
            access_type="offline", prompt="consent", state=state,
        )
        _pending_verifiers[state] = flow.code_verifier
        return url

    async def exchange_code(self, code: str, state: str) -> dict[str, Any]:
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            _CLIENT_CONFIG, scopes=_SCOPES, redirect_uri=settings.google_redirect_uri,
        )
        flow.code_verifier = _pending_verifiers.pop(state, None)
        flow.fetch_token(code=code)
        creds = flow.credentials
        return {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "expires_at": creds.expiry.replace(tzinfo=UTC).isoformat() if creds.expiry else "",
            "scopes": list(creds.scopes or _SCOPES),
        }

    async def refresh_tokens(self, user_id: str, refresh_token: str) -> dict[str, Any] | None:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=_SCOPES,
        )
        try:
            creds.refresh(GoogleAuthRequest())
            return {
                "access_token": creds.token,
                "refresh_token": creds.refresh_token,
                "expires_at": creds.expiry.replace(tzinfo=UTC).isoformat() if creds.expiry else "",
                "scopes": list(creds.scopes or _SCOPES),
            }
        except Exception:
            log.exception("google_calendar.refresh_failed")
            return None

    async def list_events(
        self, user_id: str, start_date: str,
        end_date: str | None = None, query: str | None = None, **_: Any,
    ) -> str:
        creds = await _get_valid_credentials(user_id)
        if not creds:
            return _NO_INTEGRATION_MSG

        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date) if end_date else start_dt + timedelta(days=7)
        time_min = start_dt.isoformat() + "T00:00:00Z"
        time_max = end_dt.isoformat() + "T23:59:59Z"

        try:
            service = _build_google_service(creds)
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
        self, user_id: str, title: str, start_datetime: str, end_datetime: str,
        description: str | None = None, location: str | None = None,
        attendees: list[str] | None = None, **_: Any,
    ) -> str:
        creds = await _get_valid_credentials(user_id)
        if not creds:
            return _NO_INTEGRATION_MSG

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
            service = _build_google_service(creds)
            event = service.events().insert(
                calendarId="primary", body=body,
                sendUpdates="all" if attendees else "none",
            ).execute()

            link = event.get("htmlLink", "")
            log.info("google_calendar.event_created", user_id=user_id, event_id=event["id"])
            return f"Evento criado: {title}\nLink: {link}"

        except Exception as exc:
            log.exception("google_calendar.create_failed", user_id=user_id)
            return f"Erro ao criar evento: {exc}"

    async def update_event(self, user_id: str, event_id: str, fields: dict[str, Any], **_: Any) -> str:
        creds = await _get_valid_credentials(user_id)
        if not creds:
            return _NO_INTEGRATION_MSG

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
            service = _build_google_service(creds)
            event = service.events().patch(
                calendarId="primary", eventId=event_id, body=body,
                sendUpdates="all" if "attendees" in body else "none",
            ).execute()
            log.info("google_calendar.event_updated", user_id=user_id, event_id=event_id)
            return f"Evento atualizado: {event.get('summary', event_id)}"

        except Exception as exc:
            log.exception("google_calendar.update_failed", user_id=user_id)
            return f"Erro ao atualizar evento: {exc}"

    async def delete_event(self, user_id: str, event_id: str, **_: Any) -> str:
        creds = await _get_valid_credentials(user_id)
        if not creds:
            return _NO_INTEGRATION_MSG

        try:
            service = _build_google_service(creds)
            service.events().delete(calendarId="primary", eventId=event_id).execute()
            log.info("google_calendar.event_deleted", user_id=user_id, event_id=event_id)
            return "Evento removido da agenda."

        except Exception as exc:
            log.exception("google_calendar.delete_failed", user_id=user_id)
            return f"Erro ao remover evento: {exc}"
