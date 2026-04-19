"""Intent classifier using Haiku to route user messages."""

import json
from dataclasses import dataclass
from typing import Literal

import structlog

from alfred.agent.client import CLASSIFIER_MAX_TOKENS, CLASSIFIER_MODEL, get_anthropic

log = structlog.get_logger()

IntentType = Literal["QUERY", "ACTION", "MULTI_ACTION", "CONVERSATION"]

_CLASSIFIER_PROMPT = """\
Você é um classificador de intenção para um assistente de relacionamentos.
Analise a mensagem do usuário e classifique em UMA categoria:

QUERY — o usuário quer CONSULTAR informações (listar follow-ups, buscar contatos, ver memórias, perguntar o que sabe sobre alguém)
Sinais: "mostra", "lista", "quem", "quais", "quantos", "o que eu sei", "me fala sobre"

ACTION — o usuário quer EXECUTAR uma ação sobre UM contato (criar, atualizar, registrar interação, agendar follow-up, salvar memória)
Sinais: "marca", "agenda", "falei com", "cadastra", "cria", "atualiza", "me lembra de"

MULTI_ACTION — o usuário quer EXECUTAR ações sobre MÚLTIPLOS contatos na mesma mensagem
Sinais: múltiplos nomes próprios + verbos de ação, listas de pessoas com informações

CONVERSATION — o usuário está conversando, fazendo pergunta sobre o Alfred, saudação, agradecendo
Sinais: "oi", "obrigado", "o que você faz?", "como funciona", conversa casual

Responda APENAS com JSON: {"intent": "QUERY|ACTION|MULTI_ACTION|CONVERSATION", "confidence": 0.0-1.0}

Na dúvida entre QUERY e ACTION, escolha ACTION (mais seguro).
Na dúvida entre ACTION e MULTI_ACTION, escolha MULTI_ACTION.\
"""

_VALID_INTENTS: set[IntentType] = {"QUERY", "ACTION", "MULTI_ACTION", "CONVERSATION"}
_DEFAULT = "ACTION"


@dataclass(frozen=True)
class IntentResult:
    intent: IntentType
    confidence: float


async def classify_intent(message: str) -> IntentResult:
    """Classify user message intent using Haiku. Falls back to ACTION on any error."""
    try:
        client = get_anthropic()
        response = await client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=CLASSIFIER_MAX_TOKENS,
            system=_CLASSIFIER_PROMPT,
            messages=[{"role": "user", "content": message}],
        )

        raw = response.content[0].text.strip()
        data = json.loads(raw)
        intent = data.get("intent", _DEFAULT).upper()
        confidence = float(data.get("confidence", 0.5))

        if intent not in _VALID_INTENTS:
            intent = _DEFAULT

        log.info("classifier.result", intent=intent, confidence=confidence)
        return IntentResult(intent=intent, confidence=confidence)

    except Exception:
        log.warning("classifier.fallback", exc_info=True)
        return IntentResult(intent=_DEFAULT, confidence=0.0)
