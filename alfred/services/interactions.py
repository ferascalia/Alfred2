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

    # Atualiza apenas last_interaction_at — next_nudge_at é responsabilidade do
    # set_follow_up (follow-up específico) ou do botão "Já falei" (cadência padrão)
    db.table("contacts").update({
        "last_interaction_at": happened_at_iso,
    }).eq("id", contact_id).eq("user_id", user_id).execute()

    log.info("interaction.logged", user_id=user_id, contact_id=contact_id, channel=channel)
    return (
        f"Interação registrada: {summary[:80]}...\n"
        "⚠️ Se o usuário mencionou um follow-up, prazo ou próximo encontro neste turno, "
        "chame set_follow_up AGORA antes de responder."
    )
