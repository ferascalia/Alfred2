"""Nudge worker — called by pg_cron via pg_net."""
import contextlib
from datetime import UTC, datetime
from typing import Any

import structlog
from anthropic.types import TextBlock

from alfred.agent.client import MODEL, get_anthropic
from alfred.db.client import get_db

log = structlog.get_logger()


async def process_nudge(contact_id: str) -> dict[str, Any]:
    """Generate and send a nudge for a single contact."""
    db = get_db()

    # Load contact
    contact_result = (
        db.table("contacts")
        .select("*, users(telegram_id, name)")
        .eq("id", contact_id)
        .single()
        .execute()
    )
    if not contact_result.data:
        log.warning("nudge.contact_not_found", contact_id=contact_id)
        return {"error": "contact not found"}

    contact = contact_result.data
    user = contact.get("users", {})
    telegram_id = user.get("telegram_id")

    if not telegram_id:
        return {"error": "no telegram_id for user"}

    # Load last interaction
    last_interaction = (
        db.table("interactions")
        .select("channel, summary, happened_at")
        .eq("contact_id", contact_id)
        .order("happened_at", desc=True)
        .limit(1)
        .execute()
    )

    # Load recent memories
    memories = (
        db.table("memories")
        .select("content, kind")
        .eq("contact_id", contact_id)
        .order("captured_at", desc=True)
        .limit(5)
        .execute()
    )

    # Calculate days since last contact — use contacts.last_interaction_at as source of truth.
    # The interactions table may be outdated when the user marks contacts via "Já falei"
    # (which updates contacts.last_interaction_at but does not insert an interactions record).
    days_since: int | str = "?"
    last_contact_raw = contact.get("last_interaction_at")
    if last_contact_raw:
        with contextlib.suppress(Exception):
            last_contact_dt = datetime.fromisoformat(last_contact_raw.replace("Z", "+00:00"))
            days_since = (datetime.now(UTC) - last_contact_dt).days

    # Last interaction summary — from interactions table (richer context when available)
    last_summary = "sem histórico registrado"
    if last_interaction.data:
        li = last_interaction.data[0]
        last_summary = f"via {li['channel']}: {li['summary']}"

    memory_lines = "\n".join(
        f"- [{m['kind']}] {m['content']}" for m in memories.data
    )

    # Generate rationale + draft via Claude
    prompt = f"""Você é o Alfred. Escreva um lembrete proativo para o usuário sobre o contato abaixo.

CONTATO: {contact['display_name']}
DIAS SEM CONTATO: {days_since}
ÚLTIMA INTERAÇÃO: {last_summary}
MEMÓRIAS:
{memory_lines or '(sem memórias registradas)'}

Retorne EXATAMENTE neste formato JSON (sem markdown):
{{
  "reason": "frase curta explicando por que é hora de entrar em contato (máx 100 chars)",
  "draft": "rascunho caloroso e pessoal da mensagem para o contato (máx 200 chars)"
}}"""

    client = get_anthropic()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text_blocks = [b for b in response.content if isinstance(b, TextBlock)]
    raw = "\n".join(b.text for b in text_blocks).strip()

    import json
    try:
        parsed = json.loads(raw)
        reason = parsed.get("reason", "Faz tempo que não se falam.")
        draft = parsed.get("draft", "Oi! Tudo bem?")
    except json.JSONDecodeError:
        reason = f"Faz {days_since} dias sem contato."
        draft = "Oi! Tudo bem? Estava pensando em você."

    # Save nudge record
    nudge_result = db.table("nudges").insert({
        "user_id": contact["user_id"],
        "contact_id": contact_id,
        "reason": reason,
        "suggested_action": "reach_out",
        "draft_message": draft,
        "status": "sent",
    }).execute()

    nudge_id = nudge_result.data[0]["id"]

    # Send Telegram message
    from telegram import Bot

    from alfred.bot.keyboards import nudge_keyboard
    from alfred.config import settings

    bot = Bot(token=settings.telegram_bot_token)

    company_suffix = f" ({contact['company']})" if contact.get("company") else ""
    text = (
        f"🔔 Faz **{days_since} dias** que você não fala com **{contact['display_name']}**{company_suffix}.\n\n"
        f"📝 {reason}\n\n"
        f"✍️ Sugestão de mensagem:\n_{draft}_"
    )

    await bot.send_message(
        chat_id=telegram_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=nudge_keyboard(nudge_id),
    )

    # Clear next_nudge_at so the scan doesn't re-fire every day until the user acts.
    # It will be recalculated when the user clicks "Já falei" (update_contact_after_interaction).
    db.table("contacts").update({"next_nudge_at": None}).eq("id", contact_id).execute()

    log.info("nudge.sent", contact_id=contact_id, nudge_id=nudge_id, telegram_id=telegram_id)
    return {"nudge_id": nudge_id, "contact_id": contact_id, "status": "sent"}
