"""Conversation Agent — casual chat, greetings, meta-questions. Haiku, no tools."""

from typing import Any

from alfred.agent.base import BaseAgent, GuardrailConfig
from alfred.agent.client import CLASSIFIER_MODEL, MAX_TOKENS
from alfred.agent.context import AgentContext
from alfred.agent.prompt_sections import PROMPT_BASE, PROMPT_CLOSING

_REDIRECT_SECTION = """

## Quando o usuário pedir algo que exige ferramentas

Você não tem ferramentas disponíveis. Se o usuário pedir para editar, criar, vincular, \
atualizar, registrar ou qualquer ação sobre contatos, interações, memórias ou follow-ups, \
**não diga que não consegue** e **nunca diga que a ferramenta não existe**. Em vez disso:
1. Reconheça o pedido.
2. Peça para o usuário reformular de forma mais específica. Exemplos:
   - "Para editar um contato, tente: 'atualiza o cargo do Fulano para Diretor'"
   - "Para vincular contatos, tente: 'o João reporta pro Carlos no BTG'"
   - "Para registrar uma conversa, tente: 'falei com a Maria hoje sobre o projeto'"
3. Seja breve e cortês, no tom Alfred.
"""

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
        sections = [PROMPT_BASE, _REDIRECT_SECTION, PROMPT_CLOSING]
        return "\n".join(sections) + _DATETIME_SUFFIX.format(current_date=ctx.current_date)
