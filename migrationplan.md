# Cleanup Legado: Monolítico -> Multi-Agent

## Contexto

O Alfred migrou de uma arquitetura monolítica (um LLM, um prompt, todas as tools) para multi-agent (router + agentes especializados). A transição usou feature flag (`use_multi_agent` / `multi_agent_test_ids`) para testes A/B. Após validação em produção, o cleanup remove o caminho legado.

## Arquitetura ANTES (legado)

```
Mensagem -> classifier.py (Haiku, 4 intents) -> loop.py (Sonnet, prompt monolítico) -> Resposta
```

- `alfred/agent/loop.py` — loop monolítico com todas as guardrails inline
- `alfred/agent/classifier.py` — classificador de 4 intents (QUERY/ACTION/MULTI_ACTION/CONVERSATION)
- `alfred/agent/prompts.py` — system prompt monolítico (~152 linhas)
- `alfred/agent/prompt_sections.py` — seções composáveis + `build_system_prompt()` para o loop legado
- `alfred/agent/tools/__init__.py` — continha `get_tools_for_intent()` com mapping de 4 intents

## Arquitetura DEPOIS (multi-agent)

```
Mensagem -> router.py (Haiku, 6 intents) -> orchestrator.py -> Agent especializado (Sonnet) -> Resposta
```

- `alfred/agent/router.py` — 6 intents (QUERY/CONTACT/RECORD/DRAFT/CONVERSATION/MULTI)
- `alfred/agent/orchestrator.py` — seleciona e executa agentes, suporta MULTI (cadeia sequencial)
- `alfred/agent/base.py` — BaseAgent com loop genérico + guardrails configuráveis por agente
- `alfred/agent/agents/` — agentes especializados (QueryAgent, ContactAgent, ActivityAgent, DraftingAgent, ConversationAgent)
- `alfred/agent/context.py` — AgentContext + AgentResult compartilhados
- `alfred/agent/prompt_sections.py` — seções composáveis (PROMPT_BASE, PROMPT_ACTION, etc.) usadas pelos agentes

## Arquivos DELETADOS

| Arquivo | Razão |
|---------|-------|
| `alfred/agent/loop.py` | Substituído por orchestrator.py + base.py |
| `alfred/agent/classifier.py` | Substituído por router.py (6 intents vs 4) |
| `alfred/agent/prompts.py` | Substituído por prompt_sections.py (seções composáveis) |
| `tests/test_classifier.py` | Testava classifier.py deletado |
| `tests/test_prompt_sections.py` | Testava `build_system_prompt()` e `get_tools_for_intent()` deletados |

## Arquivos MODIFICADOS

### `alfred/bot/handlers.py`
- Removido: `_use_multi_agent()` — checava feature flag + test IDs
- Removido: `_get_run_agent()` — retornava loop ou orchestrator baseado na flag
- Agora: importa `run_agent` direto de `alfred.agent.orchestrator`
- Removido: `multi_agent=...` dos log lines

### `alfred/config.py`
- Removido: `use_multi_agent: bool = False`
- Removido: `multi_agent_test_ids: str = ""`

### `alfred/agent/tools/__init__.py`
- Removido: `_READ_TOOL_NAMES`, `_WRITE_TOOL_NAMES`, `_INTENT_TOOLS` — mapping de 4 intents legados
- Removido: `get_tools_for_intent()` — só era usado pelo loop.py legado
- Mantido: re-exports de `TOOL_SCHEMAS`, `dispatch_tool`, `READ_TOOLS`, etc. (usados pelos agentes)

### `alfred/agent/prompt_sections.py`
- Removido: `_INTENT_SECTIONS` dict — mapping de 4 intents legados
- Removido: `build_system_prompt()` — só era usado pelo loop.py legado
- Mantido: todas as seções individuais (PROMPT_BASE, PROMPT_ACTION, etc.) usadas pelos agentes

### `alfred/agent/router.py`
- Removido: `_LEGACY_MAP` — traduzia "ACTION" -> "RECORD", "MULTI_ACTION" -> "MULTI"
- Era shim de compatibilidade para o período de transição

### `tests/test_handlers.py`
- Atualizado mock: `alfred.agent.loop.run_agent` -> `alfred.agent.orchestrator.run_agent`

## Env vars removidas

- `USE_MULTI_AGENT` — já não é lida
- `MULTI_AGENT_TEST_IDS` — já não é lida

Remover do Railway e do `.env` local se ainda estiverem definidas (não quebram nada, são apenas lixo).

## Verificação

1. `pytest tests/ -x` — todos os testes passam
2. Verificar no Railway que as env vars legadas não estão mais setadas
3. Deploy e teste manual no Telegram
