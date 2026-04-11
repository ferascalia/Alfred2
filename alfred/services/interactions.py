"""Interaction logging."""
from datetime import UTC, datetime

import structlog

from alfred.db.client import get_db

log = structlog.get_logger()


async def log_interaction(
    user_id: str,
    contact_id: str,
    channel: str,
    direction: str,
    summary: str,
    happened_at: str,
    sentiment: str | None = None,
) -> str:
    db = get_db()

    # Parse and validate happened_at
    try:
        dt = datetime.fromisoformat(happened_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        happened_at_iso = dt.isoformat()
    except ValueError:
        happened_at_iso = datetime.now(UTC).isoformat()

    db.table("interactions").insert({
        "user_id": user_id,
        "contact_id": contact_id,
        "channel": channel,
        "direction": direction,
        "summary": summary,
        "sentiment": sentiment,
        "happened_at": happened_at_iso,
    }).execute()

    # Update contact's last_interaction_at and next_nudge_at
    db.rpc("update_contact_after_interaction", {
        "p_contact_id": contact_id,
        "p_happened_at": happened_at_iso,
    }).execute()

    log.info("interaction.logged", user_id=user_id, contact_id=contact_id, channel=channel)
    return f"Interação registrada: {summary[:80]}..."
