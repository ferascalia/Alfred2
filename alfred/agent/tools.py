"""Tool schemas and dispatch for the Alfred agent."""
from typing import Any

import structlog

log = structlog.get_logger()

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_memories",
        "description": "Busca memórias semânticas sobre contatos. Use para responder perguntas do tipo 'o que eu sei sobre X?' ou recuperar contexto antes de rascunhar uma mensagem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto de busca em linguagem natural"},
                "contact_id": {"type": "string", "description": "ID do contato para filtrar (opcional)"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_contacts",
        "description": "Lista contatos do usuário com filtros opcionais.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Filtro por nome (opcional)"},
                "status": {"type": "string", "enum": ["active", "paused", "archived"], "default": "active"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "get_contact_digest",
        "description": "Retorna um resumo completo de um contato: dados, memórias e última interação.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string"},
            },
            "required": ["contact_id"],
        },
    },
    {
        "name": "create_contact",
        "description": "Cria um novo contato. Use quando o usuário mencionar uma pessoa nova.",
        "input_schema": {
            "type": "object",
            "properties": {
                "display_name": {"type": "string"},
                "aliases": {"type": "array", "items": {"type": "string"}, "description": "Apelidos ou variações do nome"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Ex: ['amigo', 'cliente', 'mentor']"},
                "how_we_met": {"type": "string"},
                "relationship_type": {"type": "string", "enum": ["friend", "professional", "family", "other"]},
                "company": {"type": "string"},
                "role": {"type": "string"},
                "cadence_days": {"type": "integer", "description": "Frequência de contato desejada em dias", "default": 30},
            },
            "required": ["display_name"],
        },
    },
    {
        "name": "update_contact",
        "description": "Atualiza dados de um contato existente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string"},
                "fields": {
                    "type": "object",
                    "description": "Campos a atualizar (display_name, company, role, cadence_days, etc.)",
                },
            },
            "required": ["contact_id", "fields"],
        },
    },
    {
        "name": "add_memory",
        "description": "Adiciona uma memória sobre um contato. Use quando o usuário mencionar algo relevante sobre alguém.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string"},
                "content": {"type": "string", "description": "O fato ou memória a guardar"},
                "kind": {
                    "type": "string",
                    "enum": ["personal", "professional", "milestone", "preference", "context", "other"],
                },
            },
            "required": ["contact_id", "content", "kind"],
        },
    },
    {
        "name": "log_interaction",
        "description": "Registra uma interação com um contato (conversa, encontro, ligação, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string"},
                "channel": {"type": "string", "enum": ["telegram", "whatsapp", "email", "call", "in_person", "other"]},
                "direction": {"type": "string", "enum": ["outbound", "inbound", "both"]},
                "summary": {"type": "string", "description": "Resumo do que foi falado/feito"},
                "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"], "description": "Tom geral da interação"},
                "happened_at": {"type": "string", "description": "ISO 8601 datetime, ex: '2024-01-15T14:30:00'"},
            },
            "required": ["contact_id", "channel", "direction", "summary", "happened_at"],
        },
    },
    {
        "name": "set_cadence",
        "description": "Define a cadência de contato desejada para um contato (de quantos em quantos dias).",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string"},
                "days": {"type": "integer", "description": "Intervalo em dias entre contatos"},
            },
            "required": ["contact_id", "days"],
        },
    },
    {
        "name": "archive_contact",
        "description": "Arquiva um contato (remove dos nudges ativos, mantém memórias).",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string"},
            },
            "required": ["contact_id"],
        },
    },
    {
        "name": "draft_message",
        "description": "Gera um rascunho de mensagem para enviar a um contato. Retorna apenas o texto — não envia nada.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string"},
                "purpose": {"type": "string", "description": "Objetivo da mensagem, ex: 'retomar contato', 'parabenizar pelo filho', 'follow-up sobre projeto'"},
                "tone": {"type": "string", "enum": ["warm", "professional", "casual"], "default": "warm"},
            },
            "required": ["contact_id", "purpose"],
        },
    },
]


async def dispatch_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    user_id: str,
) -> str:
    """Route tool calls to the appropriate service functions."""
    log.info("tool.dispatch", tool=tool_name, user_id=user_id)

    if tool_name == "search_memories":
        from alfred.services.memories import search_memories
        return await search_memories(user_id=user_id, **tool_input)

    if tool_name == "list_contacts":
        from alfred.services.contacts import list_contacts
        return await list_contacts(user_id=user_id, **tool_input)

    if tool_name == "get_contact_digest":
        from alfred.services.contacts import get_contact_digest
        return await get_contact_digest(user_id=user_id, **tool_input)

    if tool_name == "create_contact":
        from alfred.services.contacts import create_contact
        return await create_contact(user_id=user_id, **tool_input)

    if tool_name == "update_contact":
        from alfred.services.contacts import update_contact
        return await update_contact(user_id=user_id, **tool_input)

    if tool_name == "add_memory":
        from alfred.services.memories import add_memory
        return await add_memory(user_id=user_id, **tool_input)

    if tool_name == "log_interaction":
        from alfred.services.interactions import log_interaction
        return await log_interaction(user_id=user_id, **tool_input)

    if tool_name == "set_cadence":
        from alfred.services.contacts import set_cadence
        return await set_cadence(user_id=user_id, **tool_input)

    if tool_name == "archive_contact":
        from alfred.services.contacts import archive_contact
        return await archive_contact(user_id=user_id, **tool_input)

    if tool_name == "draft_message":
        from alfred.services.contacts import draft_message
        return await draft_message(user_id=user_id, **tool_input)

    return f"Ferramenta '{tool_name}' não reconhecida."
