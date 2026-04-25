"""Conversation Agent — casual chat, greetings, meta-questions. Haiku, no tools."""

from typing import Any

from alfred.agent.base import BaseAgent, GuardrailConfig
from alfred.agent.client import CLASSIFIER_MODEL, MAX_TOKENS
from alfred.agent.context import AgentContext
from alfred.agent.prompt_sections import PROMPT_BASE, PROMPT_CLOSING

_DATETIME_SUFFIX = (
    "\n\n## Data e hora atual\nHoje é {current_date}."
)


class ConversationAgent(BaseAgent):
    model = CLASSIFIER_MODEL
    max_tokens = MAX_TOKENS
    guardrail_config = GuardrailConfig()

    def get_tools(self) -> list[dict[str, Any]]:
        return []

    def build_prompt(self, ctx: AgentContext) -> str:
        sections = [PROMPT_BASE, PROMPT_CLOSING]
        return "\n".join(sections) + _DATETIME_SUFFIX.format(current_date=ctx.current_date)
