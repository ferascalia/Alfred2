"""Query Agent — read-only lookups, no guardrails."""

from typing import Any

from alfred.agent.base import BaseAgent, GuardrailConfig
from alfred.agent.client import MAX_TOKENS, MODEL
from alfred.agent.context import AgentContext
from alfred.agent.prompt_sections import (
    PROMPT_BASE,
    PROMPT_CLOSING,
    PROMPT_QUERY,
)
from alfred.agent.tools.schemas import READ_TOOLS

_DATETIME_SUFFIX = (
    "\n\n## Data e hora atual\nHoje é {current_date}. "
    "Use sempre esta data/hora como referência ao calcular datas. "
    "Nunca use datas do passado salvo o usuário dizer explicitamente outra."
)


class QueryAgent(BaseAgent):
    model = MODEL
    max_tokens = MAX_TOKENS
    guardrail_config = GuardrailConfig()

    def get_tools(self) -> list[dict[str, Any]]:
        return list(READ_TOOLS)

    def build_prompt(self, ctx: AgentContext) -> str:
        sections = [PROMPT_BASE, PROMPT_QUERY, PROMPT_CLOSING]
        return "\n".join(sections) + _DATETIME_SUFFIX.format(current_date=ctx.current_date)
