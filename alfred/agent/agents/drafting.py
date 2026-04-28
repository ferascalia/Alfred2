"""Drafting Agent — composes personalized messages, no guardrails."""

from typing import Any

from alfred.agent.base import BaseAgent, GuardrailConfig
from alfred.agent.client import MAX_TOKENS, MODEL
from alfred.agent.context import AgentContext
from alfred.agent.prompt_sections import (
    PROMPT_BASE,
    PROMPT_CLOSING,
    PROMPT_DRAFTING,
)
from alfred.agent.tools.schemas import (
    CORE_WRITE_TOOLS,
    DRAFT_TOOLS,
    GET_CONTACT_DIGEST_SCHEMA,
    LIST_CONTACTS_SCHEMA,
    SEARCH_MEMORIES_SCHEMA,
)

_DATETIME_SUFFIX = (
    "\n\n## Data e hora atual\nHoje é {current_date}. "
    "Use sempre esta data/hora como referência."
)


class DraftingAgent(BaseAgent):
    model = MODEL
    max_tokens = MAX_TOKENS
    guardrail_config = GuardrailConfig()

    def get_tools(self) -> list[dict[str, Any]]:
        return CORE_WRITE_TOOLS + DRAFT_TOOLS + [
            SEARCH_MEMORIES_SCHEMA,
            GET_CONTACT_DIGEST_SCHEMA,
            LIST_CONTACTS_SCHEMA,
        ]

    def build_prompt(self, ctx: AgentContext) -> str:
        sections = [PROMPT_BASE, PROMPT_DRAFTING, PROMPT_CLOSING]
        return "\n".join(sections) + _DATETIME_SUFFIX.format(current_date=ctx.current_date)
