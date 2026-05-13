"""OAuth service — store, refresh, and revoke tokens for external integrations."""

from datetime import UTC, datetime, timedelta

import structlog
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from alfred.config import settings
from alfred.db.client import get_db

log = structlog.get_logger()

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]


def build_google_auth_url(state: str) -> str:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uris": [settings.google_redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=GOOGLE_SCOPES,
        redirect_uri=settings.google_redirect_uri,
    )
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
    )
    return url


async def exchange_google_code(code: str) -> Credentials:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uris": [settings.google_redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=GOOGLE_SCOPES,
        redirect_uri=settings.google_redirect_uri,
    )
    flow.fetch_token(code=code)
    return flow.credentials


async def store_tokens(user_id: str, provider: str, creds: Credentials) -> None:
    db = get_db()
    expires_at = creds.expiry.replace(tzinfo=UTC) if creds.expiry else (
        datetime.now(UTC) + timedelta(hours=1)
    )

    db.table("user_integrations").upsert(
        {
            "user_id": user_id,
            "provider": provider,
            "access_token": creds.token,
            "refresh_token": creds.refresh_token or "",
            "token_expires_at": expires_at.isoformat(),
            "scopes": list(creds.scopes or GOOGLE_SCOPES),
            "status": "active",
            "updated_at": datetime.now(UTC).isoformat(),
        },
        on_conflict="user_id,provider",
    ).execute()
    log.info("oauth.tokens_stored", user_id=user_id, provider=provider)


async def get_google_credentials(user_id: str) -> Credentials | None:
    db = get_db()
    result = (
        db.table("user_integrations")
        .select("access_token, refresh_token, token_expires_at, scopes, status")
        .eq("user_id", user_id)
        .eq("provider", "google")
        .single()
        .execute()
    )
    if not result.data or result.data["status"] == "revoked":
        return None

    row = result.data
    expiry = datetime.fromisoformat(row["token_expires_at"]) if row["token_expires_at"] else None

    creds = Credentials(
        token=row["access_token"],
        refresh_token=row["refresh_token"] or None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=row.get("scopes") or GOOGLE_SCOPES,
        expiry=expiry.replace(tzinfo=None) if expiry else None,
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            await store_tokens(user_id, "google", creds)
            log.info("oauth.token_refreshed", user_id=user_id)
        except Exception:
            log.exception("oauth.refresh_failed", user_id=user_id)
            db.table("user_integrations").update(
                {"status": "expired", "updated_at": datetime.now(UTC).isoformat()}
            ).eq("user_id", user_id).eq("provider", "google").execute()
            return None

    return creds


async def revoke_google(user_id: str) -> bool:
    db = get_db()
    db.table("user_integrations").update(
        {"status": "revoked", "updated_at": datetime.now(UTC).isoformat()}
    ).eq("user_id", user_id).eq("provider", "google").execute()
    log.info("oauth.revoked", user_id=user_id, provider="google")
    return True


async def has_google_integration(user_id: str) -> bool:
    db = get_db()
    result = (
        db.table("user_integrations")
        .select("status")
        .eq("user_id", user_id)
        .eq("provider", "google")
        .eq("status", "active")
        .execute()
    )
    return bool(result.data)
