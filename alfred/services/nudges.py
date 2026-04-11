"""Nudge handling — action callbacks from inline keyboards."""
from datetime import UTC, datetime, timedelta

import structlog

from alfred.db.client import get_db

log = structlog.get_logger()


async def handle_nudge_action(nudge_id: str, action: str) -> str:
    db = get_db()

    nudge_result = db.table("nudges").select("*").eq("id", nudge_id).single().execute()
    if not nudge_result.data:
        return "Lembrete não encontrado."

    nudge = nudge_result.data

    if action == "copy":
        # Mark as viewed, return draft message
        db.table("nudges").update({"status": "viewed"}).eq("id", nudge_id).execute()
        return nudge["draft_message"]

    elif action == "done":
        # Log interaction + recalculate next_nudge_at
        db.table("nudges").update({
            "status": "acted",
            "acted_at": datetime.now(UTC).isoformat(),
        }).eq("id", nudge_id).execute()

        now_iso = datetime.now(UTC).isoformat()
        db.rpc("update_contact_after_interaction", {
            "p_contact_id": nudge["contact_id"],
            "p_happened_at": now_iso,
        }).execute()
        return "Interação registrada."

    elif action == "snooze":
        # Postpone next_nudge_at by 7 days
        db.table("nudges").update({"status": "snoozed"}).eq("id", nudge_id).execute()
        new_nudge = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        db.table("contacts").update({"next_nudge_at": new_nudge}).eq("id", nudge["contact_id"]).execute()
        log.info("nudge.snoozed", nudge_id=nudge_id, contact_id=nudge["contact_id"])
        return "Adiado por 7 dias."

    elif action == "mute":
        db.table("nudges").update({"status": "muted"}).eq("id", nudge_id).execute()
        db.table("contacts").update({"status": "paused"}).eq("id", nudge["contact_id"]).execute()
        log.info("nudge.muted", nudge_id=nudge_id, contact_id=nudge["contact_id"])
        return "Contato silenciado."

    return "Ação não reconhecida."
