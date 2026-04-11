"""Contact CRUD + digest + draft_message."""
import json
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


async def create_contact(user_id: str, **kwargs: Any) -> str:
    db = get_db()
    data = {"user_id": user_id, "status": "active", **kwargs}
    result = db.table("contacts").insert(data).execute()
    c = result.data[0]
    log.info("contact.created", user_id=user_id, contact_id=c["id"])
    return f"Contato **{c['display_name']}** criado com sucesso (id: {c['id']})."


async def update_contact(user_id: str, contact_id: str, fields: dict[str, Any]) -> str:
    db = get_db()
    db.table("contacts").update(fields).eq("id", contact_id).eq("user_id", user_id).execute()
    return f"Contato {contact_id} atualizado: {json.dumps(fields, ensure_ascii=False)}."


async def set_cadence(user_id: str, contact_id: str, days: int) -> str:
    db = get_db()
    db.table("contacts").update({"cadence_days": days}).eq("id", contact_id).eq("user_id", user_id).execute()
    return f"Cadência definida para {days} dias."


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
