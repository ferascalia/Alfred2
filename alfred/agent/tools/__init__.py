"""Tool schemas and dispatch, organized by agent domain.

Re-exports TOOL_SCHEMAS, dispatch_tool, and get_tools_for_intent
so existing imports (loop.py, tests) continue to work.
"""

from typing import Any

from alfred.agent.tools.dispatch import dispatch_tool
from alfred.agent.tools.schemas import (
    ALL_TOOL_SCHEMAS as TOOL_SCHEMAS,
    READ_TOOLS,
    CONTACT_WRITE_TOOLS,
    ACTIVITY_WRITE_TOOLS,
    DRAFT_TOOLS,
)

__all__ = [
    "TOOL_SCHEMAS",
    "READ_TOOLS",
    "CONTACT_WRITE_TOOLS",
    "ACTIVITY_WRITE_TOOLS",
    "DRAFT_TOOLS",
    "dispatch_tool",
    "get_tools_for_intent",
]

_READ_TOOL_NAMES = {
    "search_memories", "list_contacts", "get_contact_digest",
    "draft_message", "list_follow_ups", "get_contact_network",
}

_WRITE_TOOL_NAMES = {
    "create_contact", "update_contact", "add_memory",
    "log_interaction", "set_cadence", "archive_contact",
    "merge_contacts", "set_follow_up", "create_contact_confirmed",
    "link_contacts", "unlink_contacts",
}

_INTENT_TOOLS: dict[str, set[str]] = {
    "QUERY": _READ_TOOL_NAMES,
    "ACTION": _READ_TOOL_NAMES | _WRITE_TOOL_NAMES,
    "MULTI_ACTION": _READ_TOOL_NAMES | _WRITE_TOOL_NAMES,
    "CONVERSATION": set(),
}


def get_tools_for_intent(intent: str) -> list[dict[str, Any]]:
    """Return TOOL_SCHEMAS filtered by classified intent."""
    allowed = _INTENT_TOOLS.get(intent, _READ_TOOL_NAMES | _WRITE_TOOL_NAMES)
    if not allowed:
        return []
    return [s for s in TOOL_SCHEMAS if s["name"] in allowed]
