# Plano: Migração do Alfred para Arquitetura Multi-Agente

## Context

O Alfred é um agente de relacionamento de IA que funciona como monolito: 1 agent loop de 795 linhas, 19 tools num único dispatcher, 3 guardrails embutidos no loop, e um classificador de intenção (Haiku) que já roteia entre QUERY/ACTION/MULTI_ACTION/CONVERSATION. Funciona bem para 1 usuário, mas tem dores concretas:

- **Loop frágil**: 795 linhas de lógica interleaved com guardrails e casos especiais
- **19 tools num agente só**: confusão de seleção, difícil de testar isoladamente
- **Guardrails acoplados**: pending-actions, date-confirmation, truthfulness embutidos no loop
- **Escala de features arriscada**: adicionar voz, WhatsApp, digest = mais complexidade no monolito
- **Testes frágeis**: patches pontuais, não fixes permanentes, porque isolar o monolito é difícil

**Motivação**: Felippe quer começar a dar acesso multi-tenant para outras pessoas usarem o Alfred. O monolito atual não escala em complexidade para suportar isso.

---

## Clarificação Importante: Claude Agent SDK vs. Arquitetura Multi-Agente

O **Claude Agent SDK** (`claude-agent-sdk` no PyPI) é o motor do Claude Code como biblioteca — dá acesso a tools de arquivo/terminal/web (Read, Write, Edit, Bash, Grep) e um sistema de hooks. É excelente para construir agentes de coding/automação, mas **não é o framework certo para orquestrar agentes de domínio** como o Alfred.

Para Alfred, a abordagem correta é:

| Camada | Ferramenta |
|--------|-----------|
| LLM calls + tool use | **Anthropic Python SDK** (`anthropic`) — já usado |
| Orquestração multi-agente | **Código próprio leve** — router + agents + guardrails |
| Multi-tenant | **Supabase Auth + RLS** — já preparado no schema |

Isso dá controle total, zero lock-in, e a arquitetura mapeia para qualquer framework futuro.

---

## Arquitetura Proposta: 5 Agentes + 1 Router

### Princípio de Design: Write Scope Exclusivo + Read Tools Compartilhados

Cada agente tem seu **domínio de escrita exclusivo** (sem overlap de write tools entre agentes). Mas todos recebem **read tools compartilhados** (list_contacts, search_memories, get_contact_digest) para buscar contexto sem precisar de handoff.

Isso resolve o problema de latência: "falei com o Daniel, me lembra na sexta" vai para o **Activity Agent** que tem log_interaction + set_follow_up + list_contacts (para achar o Daniel). Um agente, zero handoffs.

### Diagrama de Fluxo

```
Mensagem do Usuário
        |
        v
┌──────────────────┐
│  Router (Haiku)  │  ~100ms, ~$0.001/msg
│  6 intents       │
└────────┬─────────┘
         |
         ├── QUERY ──────────→ Query Agent (Haiku/Sonnet) ─── 5 read tools
         |
         ├── CONTACT ────────→ Contact Agent (Sonnet) ─────── 7 write + 4 read = 11 tools
         |
         ├── RECORD ─────────→ Activity Agent (Sonnet) ────── 4 write + 4 read = 8 tools
         |
         ├── DRAFT ──────────→ Drafting Agent (Sonnet) ────── 1 write + 3 read = 4 tools
         |
         ├── CONVERSATION ───→ Conversation Agent (Haiku) ── 0 tools
         |
         └── MULTI ──────────→ Orchestrator sequencial ─────→ Agent A → Agent B
```

### Agentes Detalhados

#### 1. Router (Haiku 4.5)
- **6 intents**: QUERY, CONTACT, RECORD, DRAFT, CONVERSATION, MULTI
- Evolução do classificador atual (hoje: 4 intents)
- Extrai entidades (nomes de contatos) para acelerar o agente seguinte
- Sem tools — pura classificação + decomposição
- Fallback conservador: RECORD (mais guardrails ativos)

**Prompt do Router (adições ao classificador atual):**
```
QUERY — consultar informações (listar, buscar, ver)
CONTACT — gerenciar contatos (cadastrar, atualizar, arquivar, mesclar, vincular)
RECORD — registrar atividade (falei com, me lembra, toda semana, salva que...)
DRAFT — rascunhar mensagem para contato
CONVERSATION — conversa casual, saudação, meta-pergunta
MULTI — múltiplas ações que cruzam domínios (cadastra E falei com E me lembra)

Na dúvida: RECORD > CONTACT > QUERY (mais seguro, mais guardrails)
```

#### 2. Query Agent (Haiku 4.5 ou Sonnet 4.6)
- **5 read-only tools**: list_contacts, search_memories, get_contact_digest, list_follow_ups, get_contact_network
- Sem guardrails (leitura não tem side effects)
- Pode usar Haiku para queries simples (economia) ou Sonnet para respostas ricas
- Prompt curto: persona + "responda com base nos dados, sem inventar"

**Exemplos de roteamento:**
- "mostra os follow-ups da semana" → QUERY
- "o que eu sei sobre a Maria?" → QUERY
- "quem eu conheço no BTG?" → QUERY

#### 3. Contact Agent (Sonnet 4.6)
- **Write tools (exclusivo)**: create_contact, create_contact_confirmed, update_contact, archive_contact, merge_contacts, link_contacts, unlink_contacts
- **Read tools (compartilhado)**: list_contacts, search_memories, get_contact_digest, get_contact_network
- **Total: 11 tools**
- Guardrails: pending-actions (para "cadastra o Pedro" sem chamar create_contact)
- Prompt: persona + regras de CRUD + duplicata detection

**Exemplos de roteamento:**
- "cadastra o Pedro, ele é do BTG" → CONTACT
- "atualiza o cargo da Maria pra diretora" → CONTACT
- "mescla o Pedro S. com o Pedro Santos" → CONTACT
- "o Thiago reporta pra Stephanie" → CONTACT (link_contacts)

#### 4. Activity Agent (Sonnet 4.6) — o mais usado
- **Write tools (exclusivo)**: log_interaction, add_memory, set_follow_up, set_cadence
- **Read tools (compartilhado)**: list_contacts, search_memories, get_contact_digest, list_follow_ups
- **Total: 8 tools**
- Guardrails: pending-actions + date-confirmation + truthfulness (TODOS os 3)
- Prompt: persona + regras de ação + protocolo de confirmação de data

**Exemplos de roteamento:**
- "falei com o Daniel hoje sobre o projeto" → RECORD (log_interaction + add_memory)
- "me lembra de ligar pro João na sexta" → RECORD (set_follow_up)
- "fala com o Daniel toda segunda" → RECORD (set_cadence)
- "salva que a Maria gosta de vinho tinto" → RECORD (add_memory)

**Por que log_interaction + add_memory + set_follow_up ficam juntos:**
Esses tools SEMPRE co-ocorrem. Quando o usuário diz "falei com o Daniel hoje, ele mudou pro BTG, me lembra na sexta", o Activity Agent faz:
1. list_contacts (achar Daniel)
2. log_interaction (registrar conversa)
3. add_memory (salvar "mudou pro BTG")
4. set_follow_up (agendar sexta)
Tudo num único loop, sem handoffs.

#### 5. Drafting Agent (Sonnet 4.6)
- **Write tools (exclusivo)**: draft_message
- **Read tools (compartilhado)**: search_memories, get_contact_digest, list_contacts
- **Total: 4 tools**
- Sem guardrails (draft não executa ação)
- Prompt focado em tom, personalização, calor humano

**Exemplos de roteamento:**
- "rascunha uma mensagem pro Daniel sobre o aniversário" → DRAFT

#### 6. Conversation Agent (Haiku 4.5)
- **0 tools**
- Persona do Alfred (gentleman, cordial, em português)
- Modelo barato — economia de custo
- Responde saudações, meta-perguntas, agradecimentos

**Exemplos de roteamento:**
- "oi Alfred" → CONVERSATION
- "o que você faz?" → CONVERSATION
- "obrigado!" → CONVERSATION

### Intent MULTI: Orquestração Cross-Domain

Quando o Router detecta MULTI (ações em múltiplos domínios), o Orchestrator decompõe e executa sequencialmente:

```
"cadastra o Pedro do BTG, falei com ele hoje, me lembra na sexta"
    ↓
Router: MULTI → tasks: [CONTACT, RECORD]
    ↓
Orchestrator:
  1. Contact Agent → create_contact("Pedro", company="BTG") → retorna contact_id
  2. Activity Agent → log_interaction(contact_id) + set_follow_up(contact_id, sexta)
  3. Combina respostas → resposta unificada ao usuário
```

O Router retorna para MULTI:
```json
{
  "intent": "MULTI",
  "agents": ["CONTACT", "RECORD"],
  "entities": ["Pedro"]
}
```

### Mapeamento de Write Scope (sem overlap)

| Write Tool | Agente Dono |
|-----------|-------------|
| create_contact | Contact Agent |
| create_contact_confirmed | Contact Agent |
| update_contact | Contact Agent |
| archive_contact | Contact Agent |
| merge_contacts | Contact Agent |
| link_contacts | Contact Agent |
| unlink_contacts | Contact Agent |
| log_interaction | Activity Agent |
| add_memory | Activity Agent |
| set_follow_up | Activity Agent |
| set_cadence | Activity Agent |
| draft_message | Drafting Agent |

### Análise de Latência

| Cenário | Hoje | Multi-agente | Delta |
|---------|------|-------------|-------|
| Consulta simples | 1 Haiku + 1 Sonnet | 1 Haiku + 1 Haiku/Sonnet | = ou -custo |
| Registrar atividade | 1 Haiku + 1 Sonnet | 1 Haiku + 1 Sonnet | = |
| Cadastrar contato | 1 Haiku + 1 Sonnet | 1 Haiku + 1 Sonnet | = |
| Rascunhar mensagem | 1 Haiku + 1 Sonnet | 1 Haiku + 1 Sonnet | = |
| MULTI (2 domínios) | 1 Haiku + 1 Sonnet | 1 Haiku + 2 Sonnet | +1 call |
| Conversa casual | 1 Haiku + 1 Sonnet | 1 Haiku + 1 Haiku | -custo |

**Happy path (80%+ dos casos)**: mesma latência. MULTI adiciona +1 Sonnet call (~500ms) apenas em fluxos cross-domain.

---

## Guardrails Extraídos

### Pending-Actions (`alfred/agent/guardrails/pending_actions.py`)
- Extraído de loop.py linhas 26-186
- Regex patterns para detectar interações/follow-ups/cadências mencionados mas não executados
- **Ativo em**: Activity Agent (RECORD), Contact Agent (CONTACT)
- **Inativo em**: Query Agent, Drafting Agent, Conversation Agent
- Se detecta falta: injeta reminder e força retry (max 2x)

### Date-Confirmation (`alfred/agent/guardrails/date_confirmation.py`)
- Extraído de loop.py linhas 82-108
- Detecta "Confirmando:" + data numérica
- **Ativo em**: Activity Agent apenas (único que chama set_follow_up/log_interaction)
- Intercepta resposta antes dos outros guardrails
- Integrado com teclado inline do Telegram

### Truthfulness (`alfred/agent/guardrails/truthfulness.py`)
- Extraído de loop.py linhas 192-378
- Cross-referencia claims vs tool calls reais + DB
- **Ativo em**: Activity Agent, Contact Agent (agentes que executam ações)
- Observacional (não bloqueia) — loga warnings
- Roda por último

### Fluxo de Guardrails

```
Agente produz resposta final
    ↓
date_confirmation_check() → se True: pula outros, retorna
    ↓
pending_actions_check() → se falta: injeta reminder, retry (max 2x)
    ↓
truthfulness_check() → loga warnings (não bloqueia)
    ↓
Retorna resposta ao usuário
```

---

## Estado Compartilhado: AgentContext

```python
@dataclass
class AgentContext:
    # Identidade
    user_id: str              # UUID interno
    telegram_id: int          # Telegram user ID
    user_name: str            # display name

    # Request
    message: str              # mensagem original
    intent: str               # intent classificado
    current_date: str         # "2026-04-22 (quarta-feira, 14:30 BRT)"
    is_confirmation: bool     # True se [CONFIRMAÇÃO APROVADA]

    # Estado acumulado (mutável)
    tools_called: set[str]
    tool_calls_log: list[tuple[str, dict]]
    pending_retries: int

    # Histórico
    history: list[MessageParam]
```

- Criado fresh por request
- Passado do Router → Specialist → Guardrails
- `user_id` escopa todas as queries (já funciona assim hoje)
- Garbage-collected após o turn

---

## Multi-Tenant: O Que Muda

**O que já está pronto (zero mudança):**
- Schema com `user_id` em todas as tabelas
- RLS policies em todas as tabelas
- Services recebem `user_id` como primeiro parâmetro
- `telegram_id` → `user_id` mapping via tabela `users`

**O que precisa mudar:**
- Budget alerts: atualmente global, precisa ser per-tenant
- `_import_states` em handlers.py: dict in-memory, precisa ir pro DB/Redis
- Supabase Auth: trocar service_role por JWT per-user (Fase 3 do roadmap)

**A arquitetura multi-agente HABILITA multi-tenant** porque:
- Cada agente é stateless — `(context, message) → response`
- Zero estado global mutável (exceto `_import_states`)
- Railway escala replicas horizontalmente (tudo no Supabase)

---

## Fases de Migração

### Fase 1: Extrair e Formalizar (sem mudança de comportamento) ✅

**Objetivo**: Desacoplar guardrails, contexto e histórico do loop.py monolítico. Zero mudança de comportamento — só reorganização.

| Arquivo | Ação | O que faz |
|---------|------|-----------|
| `alfred/agent/context.py` | ✅ Criado | `AgentContext` dataclass |
| `alfred/agent/guardrails/__init__.py` | ✅ Criado | Package |
| `alfred/agent/guardrails/pending_actions.py` | ✅ Criado | Extrair `_detect_pending_actions` + regex patterns de loop.py:26-186 |
| `alfred/agent/guardrails/date_confirmation.py` | ✅ Criado | Extrair `_is_date_confirmation_prompt` de loop.py:82-108 |
| `alfred/agent/guardrails/truthfulness.py` | ✅ Criado | Extrair `_validate_response_truthfulness` de loop.py:192-378 |
| `alfred/agent/history.py` | ✅ Criado | Extrair `_load_history`, `_save_message`, `_get_or_create_user` de loop.py:393-464 |
| `alfred/agent/loop.py` | ✅ Modificado | Importa dos novos módulos (~270 linhas vs 795) |
| `tests/` | ✅ Atualizado | Imports corrigidos em test_guardrail_queries.py e test_date_confirmation.py |

**Status**: 100/100 testes passam. Comportamento idêntico ao original.

### Fase 2: BaseAgent + Tool Schemas por Agente ✅

**Objetivo**: Definir a abstração de agente e separar tool schemas por domínio.

| Arquivo | Ação | O que faz |
|---------|------|-----------|
| `alfred/agent/base.py` | ✅ Criado | `BaseAgent` ABC com `model`, `tools`, `guardrails`, `run()` genérico |
| `alfred/agent/agents/__init__.py` | ✅ Criado | Package |
| `alfred/agent/tools/__init__.py` | ✅ Criado | Package + re-exports backwards-compatible |
| `alfred/agent/tools/schemas.py` | ✅ Criado | Tool schemas organizados: READ_TOOLS (5), CONTACT_WRITE (7), ACTIVITY_WRITE (4), DRAFT (1) = 17 total |
| `alfred/agent/tools/dispatch.py` | ✅ Criado | dispatch_tool() extraído de tools.py |
| `alfred/agent/tools.py` | ✅ Removido | Substituído pelo package tools/ |

**Status**: 100/100 testes passam. Loop.py antigo funciona via re-exports em tools/__init__.py.

### Fase 3: Implementar os 5 Agentes ✅

**Objetivo**: Criar cada agente especializado com seu prompt, tools e guardrails.

| Arquivo | Ação | O que faz |
|---------|------|-----------|
| `alfred/agent/agents/query.py` | Criar | 5 read tools, Haiku/Sonnet, sem guardrails |
| `alfred/agent/agents/contact.py` | Criar | 11 tools (7 write + 4 read), pending-actions + truthfulness |
| `alfred/agent/agents/activity.py` | Criar | 8 tools (4 write + 4 read), TODOS os guardrails |
| `alfred/agent/agents/drafting.py` | Criar | 4 tools (1 write + 3 read), sem guardrails |
| `alfred/agent/agents/conversation.py` | Criar | 0 tools, Haiku, persona |
| `tests/test_agents/` | Criar | Unit tests por agente isoladamente |

**Prompt por agente (derivados de prompt_sections.py existente):**
- Query: PROMPT_BASE + PROMPT_QUERY + PROMPT_CLOSING
- Contact: PROMPT_BASE + PROMPT_ACTION + PROMPT_CLOSING (sem PROMPT_DATE_CONFIRM)
- Activity: PROMPT_BASE + PROMPT_ACTION + PROMPT_DATE_CONFIRM + PROMPT_CLOSING
- Drafting: PROMPT_BASE + PROMPT_DRAFTING (novo) + PROMPT_CLOSING
- Conversation: PROMPT_BASE + PROMPT_CLOSING (mínimo)

**Status**: 5 agentes criados. PROMPT_DRAFTING adicionado a prompt_sections.py. 100/100 testes passam. ✅

### Fase 4: Router + Orchestrator ✅

**Objetivo**: Entry point novo que roteia para agentes especializados, incluindo MULTI.

| Arquivo | Ação | O que faz |
|---------|------|-----------|
| `alfred/agent/router.py` | ✅ Criado | 6 intents (QUERY, CONTACT, RECORD, DRAFT, CONVERSATION, MULTI) com MULTI decomposition |
| `alfred/agent/orchestrator.py` | ✅ Criado | `run_agent()`: context → route → select → run → save. MULTI sequencial com propagação de entities |
| `alfred/config.py` | ✅ Modificado | `use_multi_agent: bool = False` |
| `alfred/bot/handlers.py` | ✅ Modificado | `_get_run_agent()` retorna orchestrator ou loop via feature flag |

**Status**: 100/100 testes passam. Flag OFF = loop antigo (zero mudança). Flag ON = orchestrator novo.

### Fase 5: Testar e Migrar

**Objetivo**: Validar em produção e trocar para a nova arquitetura.

1. Ligar feature flag para admin (telegram_id do Felippe) primeiro
2. Testar cada intent no Telegram:
   - "oi Alfred" → CONVERSATION → Conversation Agent (Haiku)
   - "mostra os follow-ups" → QUERY → Query Agent
   - "cadastra o Pedro do BTG" → CONTACT → Contact Agent
   - "rascunha uma msg pro Daniel" → DRAFT → Drafting Agent
   - "falei com o João, me lembra na sexta" → RECORD → Activity Agent + date confirm
   - "cadastra a Maria, falei com ela hoje sobre o projeto, me lembra na quarta" → MULTI → Contact Agent → Activity Agent
3. Verificar logs: `agent.routed`, `agent.selected`, `guardrail.result`
4. Comparar métricas de latência e custo (usage.py) entre mono e multi
5. Feature flag ON para todos
6. Monitorar 1 semana

**Critério de done**: 1 semana sem regressões.

### Fase 6: Cleanup

**Objetivo**: Remover código legado.

- Deletar `loop.py` (ou arquivar)
- Deletar `tools.py` monolítico (dispatch absorvido por tools/dispatch.py)
- Deletar `classifier.py` (absorvido pelo router.py)
- Remover feature flag de config.py e handlers.py
- Atualizar todos os testes

---

## Estrutura de Arquivos Final

```
alfred/
  agent/
    __init__.py
    context.py              # AgentContext dataclass + AgentResult
    orchestrator.py          # Entry point: route → select → run → save
    router.py                # Haiku classifier evoluído (6 intents + MULTI decomposition)
    base.py                  # BaseAgent ABC com loop genérico
    client.py                # (sem mudança) Anthropic client
    prompt_sections.py       # Prompts composáveis (+ PROMPT_DRAFTING novo)
    history.py               # Load/save histórico de conversa

    agents/                  # 5 agentes especializados
      __init__.py
      query.py               # 5 read tools, Haiku/Sonnet, sem guardrails
      contact.py             # 11 tools, contact CRUD + network
      activity.py            # 8 tools, log + memory + scheduling (mais usado)
      drafting.py            # 4 tools, composição de mensagens
      conversation.py        # 0 tools, Haiku, persona

    tools/                   # Schemas e dispatch por domínio
      __init__.py
      schemas.py             # READ_TOOLS, CONTACT_WRITE, ACTIVITY_WRITE, DRAFT_WRITE
      dispatch.py            # dispatch_tool() per-agent

    guardrails/              # Guardrails extraídos e plugáveis
      __init__.py
      pending_actions.py     # Regex missing-tool detector
      date_confirmation.py   # "Confirmando:" detector
      truthfulness.py        # Response-vs-reality validator

  bot/                       # (sem mudança estrutural)
    handlers.py              # Feature flag: orchestrator vs loop

  services/                  # (sem mudança)
  jobs/                      # (sem mudança)
  db/                        # (sem mudança)

tests/
  test_agents/               # Testes por agente
    test_query.py
    test_contact.py
    test_activity.py
    test_drafting.py
    test_conversation.py
  test_router.py             # Router com 6 intents + MULTI
  test_orchestrator.py       # End-to-end com mocks
  test_guardrails.py         # Guardrails isolados
  # ... testes existentes mantidos
```

---

## Trade-offs

### Ganhamos
- **Testabilidade**: cada agente ~100-150 linhas, testável em isolamento (vs 795 do monolito)
- **Write scope exclusivo**: impossível ter conflito de write entre agentes
- **Extensibilidade**: novo agente = novo arquivo + case no router + tools no schemas.py
- **Guardrails plugáveis**: cada agente declara quais guardrails ativa via `guardrail_config`
- **Custo otimizado**: QUERY + CONVERSATION no Haiku (economia real em volume)
- **Granularidade de tools**: Query (5), Activity (8), Contact (11), Drafting (4), Conversation (0) — vs 15-19 no monolito
- **Debuggability**: logs mostram qual agente errou, trace em arquivo pequeno
- **Multi-tenant ready**: AgentContext + stateless agents = Railway escala horizontal

### Adicionamos
- **Orquestração MULTI**: ~50 linhas extras para decompor e sequenciar agentes cross-domain
- **Router mais complexo**: 6 intents (vs 4 hoje), precisa detectar MULTI e decompor
- **Read tool overlap**: list_contacts e search_memories repetidos em 4 agentes (custo zero, só schemas duplicadas)
- **Latência MULTI**: +1 Sonnet call (~500ms) em fluxos cross-domain (~10-15% dos requests)
- **Manutenção**: orquestração é código próprio, não framework

### Escolhas explícitas de NÃO fazer
- **NÃO usar Claude Agent SDK**: é para coding agents (file/terminal/web), não orquestração de domínio
- **NÃO usar framework externo** (LangGraph, CrewAI): lock-in, overhead, Alfred é simples demais pra justificar
- **NÃO separar Memory Agent**: add_memory co-ocorre 90%+ com log_interaction — separar forçaria handoff no fluxo mais comum
- **NÃO router com Sonnet**: Haiku é suficiente para 6 intents, 10x mais barato

---

## Verificação End-to-End

### Testes Automatizados
1. `pytest tests/ -x` — todos passam (existentes + novos)
2. `pytest tests/test_agents/ -x` — cada agente isolado
3. `pytest tests/test_router.py -x` — 6 intents + MULTI decomposition
4. `pytest tests/test_orchestrator.py -x` — end-to-end com mocks
5. `pytest tests/test_guardrails.py -x` — guardrails extraídos

### Teste Manual no Telegram (com feature flag)
| Mensagem | Intent Esperado | Agente | Guardrails |
|----------|----------------|--------|------------|
| "oi Alfred" | CONVERSATION | Conversation (Haiku) | nenhum |
| "mostra os follow-ups" | QUERY | Query | nenhum |
| "quem eu conheço no BTG?" | QUERY | Query | nenhum |
| "cadastra o Pedro do BTG" | CONTACT | Contact | pending-actions |
| "atualiza o cargo da Maria" | CONTACT | Contact | pending-actions |
| "o Thiago reporta pra Stephanie" | CONTACT | Contact (link) | pending-actions |
| "falei com o João hoje" | RECORD | Activity | pending + date + truth |
| "me lembra do Daniel na sexta" | RECORD | Activity | pending + date + truth |
| "salva que a Maria gosta de sushi" | RECORD | Activity (add_memory) | pending |
| "rascunha msg pro Daniel" | DRAFT | Drafting | nenhum |
| "cadastra a Maria, falei com ela" | MULTI | Contact → Activity | todos |
| Import CSV | (handler direto) | — | — |
| Nudge callback | (handler direto) | — | — |

### Métricas a Comparar
- Latência p50/p95 por intent (structlog timestamps)
- Custo por intent (usage.py per-model)
- Taxa de erro por agente
- Guardrail fire rate (pending-actions, truthfulness warnings)

### Critério de Rollout
1. Feature flag ON para admin → 2 dias sem issues
2. Feature flag ON para todos → 1 semana sem regressões
3. Cleanup (Fase 6) → deletar código legado
