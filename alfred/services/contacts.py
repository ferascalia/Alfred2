"""Contact CRUD + digest + draft_message."""
import json
from difflib import SequenceMatcher
from typing import Any

import structlog
from anthropic.types import TextBlock

from alfred.db.client import get_db

log = structlog.get_logger()


async def list_contacts(
    user_id: str,
    search: str | None = None,
    status: str = "active",
    limit: int = 20,
) -> str:
    db = get_db()
    q = db.table("contacts").select("*").eq("user_id", user_id).eq("status", status).limit(limit)
    if search:
        q = q.ilike("display_name", f"%{search}%")
    result = q.order("display_name").execute()

    if not result.data:
        return "Nenhum contato encontrado."

    lines = []
    for c in result.data:
        last = c.get("last_interaction_at")
        last_str = f" | último contato: {last[:10]}" if last else ""
        lines.append(f"- **{c['display_name']}** (id: {c['id']}){last_str}")
    return "\n".join(lines)


async def get_contact_digest(user_id: str, contact_id: str) -> str:
    db = get_db()
    contact_result = (
        db.table("contacts")
        .select("*")
        .eq("id", contact_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not contact_result.data:
        return "Contato não encontrado."

    c = contact_result.data

    # Last interactions
    interactions = (
        db.table("interactions")
        .select("channel, summary, happened_at")
        .eq("contact_id", contact_id)
        .order("happened_at", desc=True)
        .limit(3)
        .execute()
    )

    # Recent memories
    memories = (
        db.table("memories")
        .select("content, kind, captured_at")
        .eq("contact_id", contact_id)
        .order("captured_at", desc=True)
        .limit(5)
        .execute()
    )

    lines = [
        f"**{c['display_name']}**",
        f"Empresa: {c.get('company') or '—'} | Cargo: {c.get('role') or '—'}",
        f"Cadência: a cada {c.get('cadence_days', 30)} dias",
        f"Último contato: {c.get('last_interaction_at', 'nunca')[:10] if c.get('last_interaction_at') else 'nunca'}",
        "",
        "**Memórias:**",
    ]
    for m in memories.data:
        lines.append(f"- [{m['kind']}] {m['content']}")

    if interactions.data:
        lines.append("\n**Últimas interações:**")
        for i in interactions.data:
            lines.append(f"- {i['happened_at'][:10]} via {i['channel']}: {i['summary']}")

    return "\n".join(lines)


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


async def find_similar_contacts(user_id: str, display_name: str, threshold: float = 0.75) -> list[dict]:
    db = get_db()
    result = db.table("contacts").select("id, display_name, company").eq("user_id", user_id).eq("status", "active").execute()
    similar = []
    for c in result.data:
        if _name_similarity(display_name, c["display_name"]) >= threshold:
            similar.append(c)
    return similar


async def create_contact(user_id: str, **kwargs: Any) -> str:
    display_name = kwargs.get("display_name", "")
    similar = await find_similar_contacts(user_id, display_name)
    if similar:
        dupes = "\n".join(
            f"- **{c['display_name']}** (id: `{c['id']}`)" + (f", {c['company']}" if c.get("company") else "")
            for c in similar
        )
        return (
            f"⚠️ Possível duplicata encontrada antes de criar **{display_name}**:\n{dupes}\n\n"
            "Use `merge_contacts` para mesclar, ou confirme que são pessoas diferentes para criar mesmo assim."
        )

    db = get_db()
    data = {"user_id": user_id, "status": "active", **kwargs}
    result = db.table("contacts").insert(data).execute()
    c = result.data[0]
    log.info("contact.created", user_id=user_id, contact_id=c["id"])
    return f"Contato **{c['display_name']}** criado com sucesso (id: {c['id']})."


async def create_contact_confirmed(user_id: str, **kwargs: Any) -> str:
    """Create contact skipping duplicate check."""
    db = get_db()
    data = {"user_id": user_id, "status": "active", **kwargs}
    result = db.table("contacts").insert(data).execute()
    c = result.data[0]
    log.info("contact.created", user_id=user_id, contact_id=c["id"])
    return f"Contato **{c['display_name']}** criado com sucesso (id: {c['id']})."


async def merge_contacts(user_id: str, primary_id: str, duplicate_id: str) -> str:
    """Move all data from duplicate to primary, then archive duplicate."""
    db = get_db()

    # Verify both contacts belong to user
    for cid in [primary_id, duplicate_id]:
        r = db.table("contacts").select("id, display_name").eq("id", cid).eq("user_id", user_id).execute()
        if not r.data:
            return f"Contato {cid} não encontrado."

    primary_name = db.table("contacts").select("display_name").eq("id", primary_id).execute().data[0]["display_name"]
    duplicate_name = db.table("contacts").select("display_name").eq("id", duplicate_id).execute().data[0]["display_name"]

    # Move memories
    db.table("memories").update({"contact_id": primary_id}).eq("contact_id", duplicate_id).execute()

    # Move interactions
    db.table("interactions").update({"contact_id": primary_id}).eq("contact_id", duplicate_id).execute()

    # Move nudges
    db.table("nudges").update({"contact_id": primary_id}).eq("contact_id", duplicate_id).execute()

    # Archive duplicate
    db.table("contacts").update({"status": "archived"}).eq("id", duplicate_id).execute()

    log.info("contacts.merged", primary_id=primary_id, duplicate_id=duplicate_id, user_id=user_id)
    return f"✅ **{duplicate_name}** mesclado em **{primary_name}**. Memórias e interações transferidas."


async def update_contact(user_id: str, contact_id: str, fields: dict[str, Any]) -> str:
    db = get_db()
    db.table("contacts").update(fields).eq("id", contact_id).eq("user_id", user_id).execute()
    return f"Contato {contact_id} atualizado: {json.dumps(fields, ensure_ascii=False)}."


async def set_cadence(user_id: str, contact_id: str, days: int) -> str:
    db = get_db()
    db.table("contacts").update({"cadence_days": days}).eq("id", contact_id).eq("user_id", user_id).execute()
    return f"Cadência definida para {days} dias."


async def set_follow_up(user_id: str, contact_id: str, date: str, note: str | None = None) -> str:
    """Set a specific follow-up date for a contact (overrides next_nudge_at)."""
    from datetime import date as date_type

    try:
        parsed = date_type.fromisoformat(date)
    except ValueError:
        return f"Data inválida: '{date}'. Use o formato YYYY-MM-DD (ex: '2026-04-20')."

    db = get_db()
    contact_result = (
        db.table("contacts")
        .select("display_name")
        .eq("id", contact_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not contact_result.data:
        return "Contato não encontrado."

    name = contact_result.data["display_name"]
    # Set next_nudge_at to midnight UTC on the target date — the 08:00 UTC scan will catch it
    next_nudge_at = f"{parsed.isoformat()}T00:00:00+00:00"

    db.table("contacts").update({"next_nudge_at": next_nudge_at}).eq("id", contact_id).eq("user_id", user_id).execute()

    log.info("follow_up.set", user_id=user_id, contact_id=contact_id, date=date)
    note_str = f" — motivo: {note}" if note else ""
    return f"Follow-up marcado para **{name}** no dia {parsed.strftime('%d/%m/%Y')}{note_str}."


async def archive_contact(user_id: str, contact_id: str) -> str:
    db = get_db()
    db.table("contacts").update({"status": "archived"}).eq("id", contact_id).eq("user_id", user_id).execute()
    return "Contato arquivado."


async def draft_message(
    user_id: str,
    contact_id: str,
    purpose: str,
    tone: str = "warm",
) -> str:
    """Use Claude to draft a personalized message for a contact."""
    from alfred.agent.client import MODEL, get_anthropic
    from alfred.services.memories import search_memories

    digest = await get_contact_digest(user_id=user_id, contact_id=contact_id)
    memories = await search_memories(user_id=user_id, query=purpose, contact_id=contact_id, limit=5)

    tone_guide = {
        "warm": "caloroso e pessoal, como uma mensagem de amigo próximo",
        "professional": "profissional mas amigável",
        "casual": "casual e descontraído",
    }.get(tone, "caloroso e pessoal")

    prompt = f"""Com base no contexto abaixo, escreva uma mensagem {tone_guide} para enviar a este contato.

CONTEXTO DO CONTATO:
{digest}

MEMÓRIAS RELEVANTES:
{memories}

OBJETIVO: {purpose}

Escreva APENAS o texto da mensagem, sem explicações ou aspas. A mensagem deve soar natural, como se o usuário tivesse escrito.
"""

    client = get_anthropic()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    text_blocks = [b for b in response.content if isinstance(b, TextBlock)]
    return "\n".join(b.text for b in text_blocks).strip()
