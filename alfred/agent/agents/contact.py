"""Contact Agent — contact CRUD + network, with pending-actions and truthfulness."""

from typing import Any

from alfred.agent.base import BaseAgent, GuardrailConfig
from alfred.agent.client import MAX_TOKENS, MODEL
from alfred.agent.context import AgentContext
from alfred.agent.prompt_sections import (
    PROMPT_ACTION,
    PROMPT_BASE,
    PROMPT_CLOSING,
)
from alfred.agent.tools.schemas import (
    CONTACT_WRITE_TOOLS,
    CORE_WRITE_TOOLS,
    GET_CONTACT_DIGEST_SCHEMA,
    GET_CONTACT_NETWORK_SCHEMA,
    LIST_CONTACTS_SCHEMA,
    SEARCH_MEMORIES_SCHEMA,
)

_DATETIME_SUFFIX = (
    "\n\n## Data e hora atual\nHoje é {current_date}. "
    "Use sempre esta data/hora como referência ao registrar interações "
    "(happened_at) ou calcular follow-ups. Nunca use datas do passado "
    "para happened_at — use a data de hoje salvo o usuário dizer "
    "explicitamente outra."
)


class ContactAgent(BaseAgent):
    model = MODEL
    max_tokens = MAX_TOKENS
    guardrail_config = GuardrailConfig(
        pending_actions=True,
        truthfulness=True,
    )

    def get_tools(self) -> list[dict[str, Any]]:
        return CORE_WRITE_TOOLS + CONTACT_WRITE_TOOLS + [
            LIST_CONTACTS_SCHEMA,
            SEARCH_MEMORIES_SCHEMA,
            GET_CONTACT_DIGEST_SCHEMA,
            GET_CONTACT_NETWORK_SCHEMA,
        ]

    def build_prompt(self, ctx: AgentContext) -> str:
        sections = [PROMPT_BASE, PROMPT_ACTION, PROMPT_CLOSING]
        return "\n".join(sections) + _DATETIME_SUFFIX.format(current_date=ctx.current_date)
