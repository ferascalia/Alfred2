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
    embedding = await _embed(content)
    db = get_db()
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

    lines = []
    for m in result.data:
        lines.append(f"- [{m.get('kind', '?')}] {m['content']}")
    return "\n".join(lines)
