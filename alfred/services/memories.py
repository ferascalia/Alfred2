"""Memory storage and semantic search via Voyage AI + pgvector."""
from typing import Any

import structlog

from alfred.config import settings
from alfred.db.client import get_db

log = structlog.get_logger()


def _get_voyage_client() -> Any:
    import voyageai
    return voyageai.Client(api_key=settings.voyage_api_key)


async def _embed(text: str) -> list[float]:
    import asyncio
    client = _get_voyage_client()
    # voyageai client is sync — run in executor
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: client.embed([text], model="voyage-3", input_type="query"),
    )
    return result.embeddings[0]


async def add_memory(
    user_id: str,
    contact_id: str,
    content: str,
    kind: str,
    source: str = "user_message",
) -> str:
    db = get_db()

    contact_check = (
        db.table("contacts").select("id").eq("id", contact_id).eq("user_id", user_id).execute()
    )
    if not contact_check.data:
        return (
            f"Contato com ID `{contact_id}` não encontrado. "
            "Use list_contacts para buscar o ID correto antes de salvar a memória."
        )

    embedding = await _embed(content)
    db.table("memories").insert({
        "user_id": user_id,
        "contact_id": contact_id,
        "content": content,
        "kind": kind,
        "source": source,
        "embedding": embedding,
    }).execute()
    log.info("memory.added", user_id=user_id, contact_id=contact_id, kind=kind)
    return (
        f"Memória registrada: {content}\n"
        "⚠️ ANTES de responder ao usuário, releia a mensagem original e verifique:\n"
        "• Ele disse que falou/encontrou/conversou com esta pessoa? → chame log_interaction agora.\n"
        "• Ele mencionou um dia futuro, prazo ou 'me lembra'? → chame set_follow_up agora.\n"
        "• Ele pediu cadência recorrente ('toda terça')? → chame set_cadence agora.\n"
        "Não feche o turno com 'registrado ✅' se alguma dessas ações está pendente."
    )


async def search_memories(
    user_id: str,
    query: str,
    contact_id: str | None = None,
    limit: int = 5,
) -> str:
    embedding = await _embed(query)

    db = get_db()
    # Use pgvector RPC for semantic search
    params: dict[str, Any] = {
        "query_embedding": embedding,
        "user_id_filter": user_id,
        "match_count": limit,
    }
    if contact_id:
        params["contact_id_filter"] = contact_id

    rpc_name = "match_memories_by_contact" if contact_id else "match_memories"
    result = db.rpc(rpc_name, params).execute()

    if not result.data:
        return "Nenhuma memória encontrada para essa busca."

    contact_ids = {m["contact_id"] for m in result.data if m.get("contact_id")}
    contact_map: dict[str, dict] = {}
    if contact_ids:
        contacts_result = (
            get_db()
            .table("contacts")
            .select("id, display_name, company")
            .in_("id", list(contact_ids))
            .execute()
        )
        for c in contacts_result.data or []:
            contact_map[c["id"]] = c

    lines = []
    for m in result.data:
        cid = m.get("contact_id")
        contact_info = ""
        if cid and cid in contact_map:
            c = contact_map[cid]
            company_part = f", {c['company']}" if c.get("company") else ""
            contact_info = f" (contato: {c['display_name']}{company_part}, id: {cid})"
        lines.append(f"- [{m.get('kind', '?')}] {m['content']}{contact_info}")
    return "\n".join(lines)
