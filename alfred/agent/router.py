"""Router — classifies user messages into 6 intents for multi-agent dispatch."""

import json
from dataclasses import dataclass, field
from typing import Literal

import structlog

from alfred.agent.client import CLASSIFIER_MAX_TOKENS, CLASSIFIER_MODEL, get_anthropic
from alfred.services.usage import record_usage

log = structlog.get_logger()

IntentType = Literal[
    "QUERY", "CONTACT", "RECORD", "DRAFT", "CONVERSATION", "MULTI"
]

_ROUTER_PROMPT = """\
Você é um classificador de intenção para um assistente de relacionamentos.
Analise a mensagem do usuário e classifique em UMA categoria:

QUERY — consultar informações (listar follow-ups, buscar contatos, ver memórias, perguntar o que sabe sobre alguém)
Sinais: "mostra", "lista", "quem", "quais", "quantos", "o que eu sei", "me fala sobre"

CONTACT — gerenciar contatos (cadastrar, atualizar, arquivar, mesclar, vincular)
Sinais: "cadastra", "cria contato", "atualiza o cargo", "mescla", "arquiva", "o X reporta pro Y"

RECORD — registrar atividade (interação, memória, follow-up, cadência)
Sinais: "falei com", "me lembra", "toda terça", "salva que", "marca follow-up"

DRAFT — rascunhar mensagem para contato
Sinais: "rascunha", "escreve uma mensagem", "monta um texto"

CONVERSATION — conversa casual, saudação, meta-pergunta sobre o Alfred
Sinais: "oi", "obrigado", "o que você faz?", "como funciona"

MULTI — múltiplas ações que cruzam domínios (cadastrar E registrar interação, cadastrar E follow-up)
Sinais: pessoa nova + interação, pessoa nova + follow-up, múltiplos domínios na mesma frase

Responda APENAS com JSON:
{"intent": "QUERY|CONTACT|RECORD|DRAFT|CONVERSATION|MULTI", "confidence": 0.0-1.0, "agents": ["CONTACT","RECORD"]}

O campo "agents" só é necessário quando intent é MULTI — lista os agentes na ordem de execução.

Na dúvida: RECORD > CONTACT > QUERY (mais seguro, mais guardrails).\
"""

_VALID_INTENTS: set[IntentType] = {
    "QUERY", "CONTACT", "RECORD", "DRAFT", "CONVERSATION", "MULTI",
}
_DEFAULT: IntentType = "RECORD"

@dataclass(frozen=True)
class RouteResult:
    intent: IntentType
    confidence: float
    agents: list[str] = field(default_factory=list)


async def classify(message: str) -> RouteResult:
    """Classify user message into one of 6 intents. Falls back to RECORD on error."""
    try:
        client = get_anthropic()
        response = await client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=CLASSIFIER_MAX_TOKENS,
            system=_ROUTER_PROMPT,
            messages=[{"role": "user", "content": message}],
        )

        usage = response.usage
        await record_usage(
            model=CLASSIFIER_MODEL,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )

        raw = response.content[0].text.strip()
        data = json.loads(raw)
        intent = data.get("intent", _DEFAULT).upper()
        confidence = float(data.get("confidence", 0.5))

        if intent not in _VALID_INTENTS:
            intent = _DEFAULT

        agents = data.get("agents", [])
        if intent == "MULTI" and not agents:
            agents = ["RECORD"]
            intent = "RECORD"

        log.info("router.result", intent=intent, confidence=confidence, agents=agents)
        return RouteResult(intent=intent, confidence=confidence, agents=agents)

    except Exception:
        log.warning("router.fallback", exc_info=True)
        return RouteResult(intent=_DEFAULT, confidence=0.0)
