# alfred/services/oauth.py
"""Generic OAuth token storage — provider-agnostic CRUD for user_integrations table."""

from datetime import UTC, datetime

import structlog

from alfred.db.client import get_db

log = structlog.get_logger()


async def store_tokens(user_id: str, provider_slug: str, token_data: dict) -> None:
    db = get_db()
    db.table("user_integrations").upsert(
        {
            "user_id": user_id,
            "provider": provider_slug,
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token", ""),
            "token_expires_at": token_data.get("expires_at", ""),
            "scopes": token_data.get("scopes", []),
            "status": "active",
            "updated_at": datetime.now(UTC).isoformat(),
        },
        on_conflict="user_id,provider",
    ).execute()
    log.info("oauth.tokens_stored", user_id=user_id, provider=provider_slug)


async def get_tokens(user_id: str, provider_slug: str) -> dict | None:
    db = get_db()
    result = (
        db.table("user_integrations")
        .select("access_token, refresh_token, token_expires_at, scopes, status")
        .eq("user_id", user_id)
        .eq("provider", provider_slug)
        .single()
        .execute()
    )
    if not result.data or result.data["status"] in ("revoked", "expired"):
        return None
    return result.data


async def has_integration(user_id: str, provider_slug: str) -> bool:
    db = get_db()
    result = (
        db.table("user_integrations")
        .select("status")
        .eq("user_id", user_id)
        .eq("provider", provider_slug)
        .eq("status", "active")
        .execute()
    )
    return bool(result.data)


async def revoke_integration(user_id: str, provider_slug: str) -> bool:
    db = get_db()
    db.table("user_integrations").update(
        {"status": "revoked", "updated_at": datetime.now(UTC).isoformat()}
    ).eq("user_id", user_id).eq("provider", provider_slug).execute()
    log.info("oauth.revoked", user_id=user_id, provider=provider_slug)
    return True


async def mark_expired(user_id: str, provider_slug: str) -> None:
    db = get_db()
    db.table("user_integrations").update(
        {"status": "expired", "updated_at": datetime.now(UTC).isoformat()}
    ).eq("user_id", user_id).eq("provider", provider_slug).execute()


async def get_active_calendar_provider(user_id: str) -> str | None:
    db = get_db()
    result = (
        db.table("user_integrations")
        .select("provider")
        .eq("user_id", user_id)
        .eq("status", "active")
        .execute()
    )
    if not result.data:
        return None
    from alfred.integrations.registry import list_providers_by_category
    calendar_slugs = {p.slug for p in list_providers_by_category("calendar")}
    for row in result.data:
        if row["provider"] in calendar_slugs:
            return row["provider"]
    return None
