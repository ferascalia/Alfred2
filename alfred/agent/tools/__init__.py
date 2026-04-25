"""Tool schemas and dispatch, organized by agent domain."""

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
]
