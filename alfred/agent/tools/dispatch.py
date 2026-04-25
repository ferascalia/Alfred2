"""Tool dispatch — routes tool calls to service functions."""

from typing import Any

import structlog

log = structlog.get_logger()

_WEEKDAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


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
        weekday_str = tool_input.get("weekday")
        weekday_int = _WEEKDAY_MAP[weekday_str] if weekday_str else None
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

    if tool_name == "link_contacts":
        from alfred.services.contacts import link_contacts
        return await link_contacts(user_id=user_id, **tool_input)

    if tool_name == "unlink_contacts":
        from alfred.services.contacts import unlink_contacts
        return await unlink_contacts(user_id=user_id, **tool_input)

    if tool_name == "get_contact_network":
        from alfred.services.contacts import get_contact_network
        return await get_contact_network(user_id=user_id, **tool_input)

    return f"Ferramenta '{tool_name}' não reconhecida."
