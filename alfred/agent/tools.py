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
        "description": "Lista contatos do usuário. Busca por nome OU empresa/organização.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Filtro por nome ou empresa (opcional). Ex: 'BTG Pactual', 'Maria', 'Google'"},
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
        "description": (
            "Cria um novo contato. Use quando o usuário mencionar uma pessoa nova. "
            "CRÍTICO: criar contato NUNCA é o passo final quando o usuário também mencionou "
            "uma interação ('falei com ele hoje'), data ('quarta'), follow-up ('me lembra'), "
            "ou cadência ('toda terça'). Depois de criar, você DEVE chamar log_interaction e/ou "
            "set_follow_up e/ou set_cadence no mesmo turno antes de responder. Não confie na memória — "
            "releia a mensagem do usuário e execute TODAS as ações pedidas."
        ),
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
                "cadence_days": {"type": "integer", "description": "Frequência de contato desejada em dias", "default": 15},
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
        "description": "Registra uma interação com um contato (conversa, encontro, ligação, etc.). Atualiza apenas o histórico — não agenda o próximo contato. Se o usuário mencionar um prazo ('em 2 dias', 'semana que vem'), chame set_follow_up logo depois.",
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
        "description": (
            "Define a cadência de contato desejada. "
            "Use 'weekday' quando o usuário quiser ser lembrado num dia fixo da semana "
            "(ex: 'toda terça', 'toda segunda'). "
            "Quando weekday é informado, days é opcional (padrão 7). "
            "Omitir weekday volta para cadência por dias e limpa qualquer dia fixo anterior."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string"},
                "days": {
                    "type": "integer",
                    "description": "Intervalo em dias entre contatos (ignorado se weekday for informado)",
                    "default": 7,
                },
                "weekday": {
                    "type": "string",
                    "enum": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
                    "description": "Dia fixo da semana para o lembrete. Omitir para cadência por dias.",
                },
            },
            "required": ["contact_id"],
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
    {
        "name": "merge_contacts",
        "description": "Mescla dois contatos duplicados. Move todas as memórias, interações e nudges do duplicado para o principal, depois arquiva o duplicado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "primary_id": {"type": "string", "description": "ID do contato que será mantido"},
                "duplicate_id": {"type": "string", "description": "ID do contato duplicado que será arquivado"},
            },
            "required": ["primary_id", "duplicate_id"],
        },
    },
    {
        "name": "set_follow_up",
        "description": (
            "Marca um follow-up para um contato em uma data específica. "
            "Use SEMPRE que o usuário mencionar um dia futuro ou prazo: 'me lembra na sexta', "
            "'marca para quarta', 'follow-up em 10 dias', 'preciso falar com ele em 2 dias'. "
            "Calcule a data absoluta a partir de hoje (a data atual está no system prompt) "
            "e passe no formato YYYY-MM-DD. "
            "Se um create_contact foi chamado antes neste turno, use o id retornado. "
            "Sempre chame APÓS log_interaction quando ambos forem necessários no mesmo turno. "
            "NUNCA diga ao usuário que marcou um follow-up sem ter chamado esta ferramenta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string"},
                "date": {"type": "string", "description": "Data do follow-up no formato YYYY-MM-DD (ex: '2026-04-20')"},
                "note": {"type": "string", "description": "Opcional: motivo ou contexto do follow-up (ex: 'perguntar sobre o novo emprego')"},
            },
            "required": ["contact_id", "date"],
        },
    },
    {
        "name": "list_follow_ups",
        "description": (
            "Lista os follow-ups agendados do usuário até uma data limite. "
            "Use SEMPRE que o usuário perguntar quais follow-ups, lembretes, "
            "compromissos ou reminders ele tem marcados (ex: 'quais meus follow-ups "
            "dessa semana?', 'o que tenho pra amanhã?', 'que lembretes eu marquei?'). "
            "NUNCA responda essa pergunta de memória nem a partir do histórico de chat — "
            "a única fonte de verdade é esta ferramenta. "
            "Calcule until_date a partir da data atual (está no system prompt): "
            "'essa semana' = domingo da semana atual, 'amanhã' = amanhã, "
            "'próxima semana' = domingo da semana seguinte, sem referência temporal = hoje + 7 dias."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "until_date": {
                    "type": "string",
                    "description": "Data limite inclusiva no formato YYYY-MM-DD (ex: '2026-04-20')",
                },
            },
            "required": ["until_date"],
        },
    },
    {
        "name": "create_contact_confirmed",
        "description": "Cria um contato mesmo que já exista alguém com nome similar. Use apenas quando o usuário confirmar que são pessoas diferentes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "display_name": {"type": "string"},
                "aliases": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "how_we_met": {"type": "string"},
                "relationship_type": {"type": "string", "enum": ["friend", "professional", "family", "other"]},
                "company": {"type": "string"},
                "role": {"type": "string"},
                "cadence_days": {"type": "integer", "default": 15},
            },
            "required": ["display_name"],
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
        _weekday_map = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
        }
        weekday_str = tool_input.get("weekday")
        weekday_int = _weekday_map[weekday_str] if weekday_str else None
        return await set_cadence(
            user_id=user_id,
            contact_id=tool_input["contact_id"],
            days=tool_input.get("days", 7),
            weekday=weekday_int,
        )

    if tool_name == "archive_contact":
        from alfred.services.contacts import archive_contact
        return await archive_contact(user_id=user_id, **tool_input)

    if tool_name == "draft_message":
        from alfred.services.contacts import draft_message
        return await draft_message(user_id=user_id, **tool_input)

    if tool_name == "set_follow_up":
        from alfred.services.contacts import set_follow_up
        return await set_follow_up(user_id=user_id, **tool_input)

    if tool_name == "list_follow_ups":
        from alfred.services.contacts import list_upcoming_follow_ups
        return await list_upcoming_follow_ups(user_id=user_id, **tool_input)

    if tool_name == "merge_contacts":
        from alfred.services.contacts import merge_contacts
        return await merge_contacts(user_id=user_id, **tool_input)

    if tool_name == "create_contact_confirmed":
        from alfred.services.contacts import create_contact_confirmed
        return await create_contact_confirmed(user_id=user_id, **tool_input)

    return f"Ferramenta '{tool_name}' não reconhecida."
