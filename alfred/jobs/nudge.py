"""Nudge worker — called by pg_cron via pg_net."""
import json
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

    # Load last interaction from interactions table (rich context)
    last_interaction = (
        db.table("interactions")
        .select("channel, summary, happened_at")
        .eq("contact_id", contact_id)
        .order("happened_at", desc=True)
        .limit(1)
        .execute()
    )

    memories = (
        db.table("memories")
        .select("content, kind")
        .eq("contact_id", contact_id)
        .order("captured_at", desc=True)
        .limit(5)
        .execute()
    )

    # --- Days since last contact ---
    # Source of truth: contacts.last_interaction_at, fallback to created_at
    days_since: int | None = None
    last_contact_raw = contact.get("last_interaction_at") or contact.get("created_at")
    if last_contact_raw:
        try:
            last_contact_dt = datetime.fromisoformat(last_contact_raw.replace("Z", "+00:00"))
            days_since = (datetime.now(UTC) - last_contact_dt).days
        except (ValueError, TypeError):
            log.warning("nudge.date_parse_error", contact_id=contact_id, raw=last_contact_raw)

    # --- Last interaction summary ---
    last_summary = ""
    if last_interaction.data:
        li = last_interaction.data[0]
        last_summary = f"Último contato: {li['channel']} — {li['summary']}"
    elif contact.get("last_interaction_at"):
        date_str = contact["last_interaction_at"][:10]
        last_summary = f"Último contato registrado em {date_str} (sem detalhes)"

    # --- Nudge type detection ---
    follow_up_note = contact.get("follow_up_note")
    has_history = bool(contact.get("last_interaction_at"))

    if follow_up_note:
        nudge_type = "scheduled"
    elif not has_history:
        nudge_type = "first_contact"
    else:
        nudge_type = "reengagement"

    # --- Build context for Claude ---
    memory_lines = "\n".join(
        f"- [{m['kind']}] {m['content']}" for m in memories.data
    )

    context_parts = [
        f"CONTATO: {contact['display_name']}",
        f"EMPRESA: {contact.get('company') or 'não informada'}",
        f"RELAÇÃO: {contact.get('relationship_type') or 'não definida'}",
        f"TAGS: {', '.join(contact.get('tags') or []) or 'nenhuma'}",
    ]
    if last_summary:
        context_parts.append(f"ÚLTIMO CONTATO: {last_summary}")
    else:
        context_parts.append("PRIMEIRO CONTATO — nunca interagiram")
    if days_since is not None:
        context_parts.append(f"DIAS DESDE ÚLTIMO CONTATO: {days_since}")
    if follow_up_note:
        context_parts.append(f"MOTIVO DO FOLLOW-UP: {follow_up_note}")
    context_parts.append(f"MEMÓRIAS:\n{memory_lines or '(nenhuma memória registrada)'}")

    context_block = "\n".join(context_parts)

    # --- Instruction by nudge type ---
    if nudge_type == "scheduled":
        instruction = (
            "O usuário AGENDOU este follow-up intencionalmente. "
            "O 'reason' deve mencionar o motivo do follow-up. "
            "O 'draft' deve ser uma mensagem natural que retome o assunto do follow-up."
        )
    elif nudge_type == "first_contact":
        instruction = (
            "Este é um NOVO contato — nunca houve interação. "
            "O 'reason' deve sugerir por que vale iniciar contato (use tags, empresa, contexto). "
            "O 'draft' deve ser uma primeira mensagem curta e natural — não se apresente formalmente, "
            "apenas puxe assunto de forma leve baseado no contexto disponível."
        )
    else:
        instruction = (
            "Contato de rotina — faz tempo que não se falam. "
            "O 'reason' deve lembrar por que este contato é importante (use memórias/tags). "
            "O 'draft' deve retomar a conversa de forma natural, referenciando algo das memórias se possível."
        )

    prompt = f"""Você é o Alfred, assistente de relacionamentos. Gere um lembrete para o usuário.

{context_block}

INSTRUÇÕES:
{instruction}

REGRAS DO DRAFT:
- Máximo 200 caracteres
- Tom natural, como se o próprio usuário tivesse escrito
- Use informações das memórias para personalizar
- Nunca use linguagem formal excessiva ("permita-me", "prezado", "venho por meio desta")
- Se não houver contexto suficiente, uma mensagem simples e calorosa é melhor que uma forçada

Retorne EXATAMENTE neste formato JSON (sem markdown):
{{"reason": "frase curta (máx 100 chars)", "draft": "mensagem para o contato (máx 200 chars)"}}"""

    client = get_anthropic()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text_blocks = [b for b in response.content if isinstance(b, TextBlock)]
    raw = "\n".join(b.text for b in text_blocks).strip()

    try:
        parsed = json.loads(raw)
        reason = parsed.get("reason", "Faz tempo que não se falam.")
        draft = parsed.get("draft", "Oi! Tudo bem?")
    except json.JSONDecodeError:
        log.warning("nudge.json_parse_error", contact_id=contact_id, raw=raw[:200])
        reason = "Faz tempo que não se falam."
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

    # --- Telegram message adapted by nudge type ---
    from telegram import Bot

    from alfred.bot.keyboards import nudge_keyboard
    from alfred.config import settings

    bot = Bot(token=settings.telegram_bot_token)

    name = contact["display_name"]
    company_suffix = f" ({contact['company']})" if contact.get("company") else ""

    if nudge_type == "scheduled":
        header = f"📌 Follow-up agendado com **{name}**{company_suffix}"
        if follow_up_note:
            header += f"\n💬 Motivo: _{follow_up_note}_"
    elif nudge_type == "first_contact":
        header = f"👋 Hora de conhecer **{name}**{company_suffix}"
    else:
        days_label = f"**{days_since} dias**" if days_since is not None else "**algum tempo**"
        header = f"🔔 Faz {days_label} sem falar com **{name}**{company_suffix}"

    text = f"{header}\n\n📝 {reason}\n\n✍️ Sugestão de mensagem:\n_{draft}_"

    await bot.send_message(
        chat_id=telegram_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=nudge_keyboard(nudge_id),
    )

    # Clear next_nudge_at (and follow_up_note if present) so the scan doesn't re-fire.
    update_data: dict[str, object] = {"next_nudge_at": None}
    if follow_up_note:
        update_data["follow_up_note"] = None
    db.table("contacts").update(update_data).eq("id", contact_id).execute()

    log.info("nudge.sent", contact_id=contact_id, nudge_id=nudge_id, nudge_type=nudge_type)
    return {"nudge_id": nudge_id, "contact_id": contact_id, "status": "sent"}
