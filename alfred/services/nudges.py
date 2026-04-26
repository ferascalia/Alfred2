"""Nudge handling — action callbacks from inline keyboards."""
from datetime import UTC, datetime, timedelta

import structlog

from alfred.db.client import get_db

log = structlog.get_logger()


async def handle_nudge_action(nudge_id: str, action: str, user_id: str) -> str:
    db = get_db()

    nudge_result = (
        db.table("nudges")
        .select("*")
        .eq("id", nudge_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
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

        db.table("interactions").insert({
            "user_id": nudge["user_id"],
            "contact_id": nudge["contact_id"],
            "channel": "other",
            "direction": "outbound",
            "summary": "Contato realizado (via lembrete)",
            "sentiment": "neutral",
            "happened_at": now_iso,
        }).execute()

        db.rpc("update_contact_after_interaction", {
            "p_contact_id": nudge["contact_id"],
            "p_happened_at": now_iso,
        }).execute()
        return "Interação registrada."

    elif action == "snooze":
        db.table("nudges").update({"status": "snoozed"}).eq("id", nudge_id).execute()

        # Se o contato tem cadência por dia da semana, avança para a próxima ocorrência
        contact_result = (
            db.table("contacts")
            .select("nudge_weekday")
            .eq("id", nudge["contact_id"])
            .single()
            .execute()
        )
        nudge_weekday = contact_result.data.get("nudge_weekday") if contact_result.data else None

        if nudge_weekday is not None:
            # Python weekday(): 0=Seg…6=Dom — mesma convenção que nudge_weekday
            today = datetime.now(UTC).date()
            days_until = (nudge_weekday - today.weekday() + 7) % 7
            if days_until == 0:
                days_until = 7
            next_date = today + timedelta(days=days_until)
            new_nudge = datetime(next_date.year, next_date.month, next_date.day, tzinfo=UTC).isoformat()
            msg = f"Adiado para a próxima ocorrência agendada."
        else:
            new_nudge = (datetime.now(UTC) + timedelta(days=7)).isoformat()
            msg = "Adiado por 7 dias."

        db.table("contacts").update({"next_nudge_at": new_nudge}).eq("id", nudge["contact_id"]).execute()
        log.info("nudge.snoozed", nudge_id=nudge_id, contact_id=nudge["contact_id"])
        return msg

    elif action == "mute":
        db.table("nudges").update({"status": "muted"}).eq("id", nudge_id).execute()
        db.table("contacts").update({"status": "paused"}).eq("id", nudge["contact_id"]).execute()
        log.info("nudge.muted", nudge_id=nudge_id, contact_id=nudge["contact_id"])
        return "Contato silenciado."

    return "Ação não reconhecida."
