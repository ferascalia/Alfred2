# Plano Fase 3 — Multi-Tenant do Alfred

## Contexto

O Alfred hoje funciona para 1 usuário. A Fase 3 do roadmap transforma-o em SaaS multi-tenant: cada usuário do Telegram tem seus próprios contatos, memórias e nudges, sem ver dados de ninguém. O objetivo imediato é abrir para 4-5 testers (sem cobrança), com arquitetura que suporte até 50 usuários. O plano também define 4 opções de pricing para quando a monetização começar.

**Problema encontrado:** O banco tem RLS (Row Level Security) habilitado, mas as policies usam `auth.uid()` e o app usa `service_role_key` — que **bypassa todas as policies**. Isolamento hoje é só na camada de aplicação (`.eq("user_id", user_id)`), frágil e com brechas.

---

## Arquitetura de Isolamento de Dados (Como Ninguém Vê Dados Alheios)

### 4 Camadas de Proteção

```
┌─────────────────────────────────────────────────────┐
│ Camada 1: Telegram Identity (Entrada)               │
│ telegram_id é autêntico — Telegram garante via       │
│ webhook + secret token. Ninguém falsifica.           │
├─────────────────────────────────────────────────────┤
│ Camada 2: Application-Layer Filtering (Principal)    │
│ TODAS as queries incluem .eq("user_id", user_id).    │
│ user_id vem do orchestrator (resolve telegram_id →   │
│ UUID). Tools recebem via AgentContext, não do input.  │
├─────────────────────────────────────────────────────┤
│ Camada 3: HMAC Signing (Callbacks)                  │
│ Botões inline (nudge, import) assinados com HMAC.    │
│ Impede manipulação de IDs no callback_data.          │
├─────────────────────────────────────────────────────┤
│ Camada 4: RLS Safety Net (Defesa em Profundidade)    │
│ Policies atualizadas para usar session variable.     │
│ Se alguma query escapar sem filtro, RLS bloqueia.    │
└─────────────────────────────────────────────────────┘
```

**Por que NÃO usar JWT per-user agora:** Para 50 usuários interagindo só via Telegram (sem frontend web), JWT adiciona complexidade significativa (mint tokens, gerenciar clients por request, middleware) sem benefício proporcional. O `telegram_id` já é verificado pelo webhook. JWT faz sentido na Fase 3.5 quando houver dashboard web.

---

## Vulnerabilidades de Segurança Encontradas (Corrigir PRIMEIRO)

| Vulnerabilidade | Arquivo | Severidade |
|---|---|---|
| `handle_nudge_action(nudge_id)` não verifica se o nudge pertence ao usuário que clicou | `alfred/services/nudges.py:11` | ALTA |
| Callback data sem assinatura — nudge_id, contact_id, user_id expostos nos botões | `alfred/bot/keyboards.py` (todas as funções) | ALTA |
| `import_preview_keyboard` embute `user_id` no callback_data sem verificação | `alfred/bot/keyboards.py:50-75` | ALTA |
| `get_monthly_spend()` soma TODOS os usuários globalmente | `alfred/services/usage.py` | MEDIA |
| `api_usage` tem RLS habilitado mas 0 policies | `supabase/migrations/0007` | BAIXA |

---

## Implementação — 5 Fases Sequenciais

### Fase 3.0 — Correções de Segurança (BLOQUEANTE)

**Arquivos a modificar:**

1. **`alfred/services/nudges.py`** — adicionar parâmetro `user_id` a `handle_nudge_action()`:
   ```python
   async def handle_nudge_action(nudge_id: str, action: str, user_id: str) -> str:
       # Adicionar .eq("user_id", user_id) na query do nudge
   ```

2. **`alfred/bot/signing.py`** (NOVO) — módulo HMAC para callbacks:
   ```python
   sign_callback(data: str) -> str      # Retorna "data|hmac16"
   verify_callback(signed: str) -> str | None  # Verifica e retorna data ou None
   ```
   Usar `settings.webhook_secret` como chave HMAC.

3. **`alfred/bot/keyboards.py`** — envolver todo `callback_data` com `sign_callback()`

4. **`alfred/bot/handlers.py`** — em `callback_handler()`:
   - Verificar HMAC antes de processar qualquer callback
   - Em `_handle_nudge_callback()`: resolver `user_id` do `telegram_id` (não do callback)
   - Em `_handle_import_callback()`: idem

5. **Testes**: `tests/test_signing.py`, atualizar `tests/test_handlers.py`

---

### Fase 3.1 — Tracking de Uso Per-User (Fundação)

**Migration `supabase/migrations/0009_multi_tenant_users.sql`:**
```sql
-- Colunas no users
ALTER TABLE users ADD COLUMN tier TEXT NOT NULL DEFAULT 'free'
    CHECK (tier IN ('free', 'personal', 'professional', 'business'));
ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'suspended', 'churned'));
ALTER TABLE users ADD COLUMN monthly_token_budget_usd NUMERIC(10,4) DEFAULT 0.50;
ALTER TABLE users ADD COLUMN max_contacts INT NOT NULL DEFAULT 25;
ALTER TABLE users ADD COLUMN max_messages_per_day INT NOT NULL DEFAULT 15;
ALTER TABLE users ADD COLUMN invited_by UUID REFERENCES users(id);

-- Invite codes
CREATE TABLE invite_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT UNIQUE NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free',
    created_by UUID REFERENCES users(id),
    used_by UUID REFERENCES users(id),
    used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index para gasto mensal per-user
CREATE INDEX idx_api_usage_user_month ON api_usage(user_id, created_at)
    WHERE user_id IS NOT NULL;

-- Função de gasto mensal per-user
CREATE OR REPLACE FUNCTION get_user_monthly_spend(p_user_id UUID)
RETURNS NUMERIC LANGUAGE sql STABLE AS $$
    SELECT COALESCE(SUM(cost_usd), 0)
    FROM api_usage
    WHERE user_id = p_user_id
      AND created_at >= date_trunc('month', now());
$$;
```

**Arquivos a modificar:**
- `alfred/services/usage.py` — adicionar `get_user_monthly_spend()` e `get_user_daily_messages()`
- `alfred/db/types.py` — atualizar `UserRow` com novos campos
- `alfred/main.py` — `/admin/usage` mostrar breakdown per-user

---

### Fase 3.2 — Sistema de Tiers e Limites

**Novo arquivo: `alfred/services/limits.py`**
```python
TIER_LIMITS = {
    "free":         {"max_contacts": 25,   "max_messages_day": 15,  "max_memories": 100,   "voice": False, "budget_usd": 0.50},
    "personal":     {"max_contacts": 100,  "max_messages_day": 50,  "max_memories": 500,   "voice": True,  "budget_usd": 2.00},
    "professional": {"max_contacts": 300,  "max_messages_day": 100, "max_memories": 2000,  "voice": True,  "budget_usd": 5.00},
    "business":     {"max_contacts": 1000, "max_messages_day": 250, "max_memories": 10000, "voice": True,  "budget_usd": 15.00},
}

async def check_limits(user_id: str) -> tuple[bool, str]:
    """Retorna (permitido, razão). Chamar antes de run_agent()."""
```

**Pontos de enforcement:**
- `alfred/agent/orchestrator.py:38` — `check_limits()` antes do router
- `alfred/services/contacts.py` — contagem antes de `create_contact()`
- `alfred/services/memories.py` — contagem antes de `add_memory()`
- `alfred/bot/handlers.py` — gate de voz no `voice_handler()`

**Novo comando: `/status`** — mostra tier, uso do mês, limites restantes

---

### Fase 3.3 — Controle de Acesso e Onboarding

**Novo arquivo: `alfred/services/access.py`**
```python
async def check_access(telegram_id: int) -> bool
async def validate_invite_code(code: str) -> dict | None
async def create_invite_code(created_by: str, tier: str) -> str
```

**Novo arquivo: `alfred/bot/admin_handlers.py`** — comandos admin via Telegram:
- `/admin_invite [tier]` — gera código de convite
- `/admin_users` — lista usuários ativos
- `/admin_set_tier [telegram_id] [tier]` — muda tier

**Modificar: `alfred/bot/handlers.py`** — gate no `start_handler()`:
```python
# Fase 3A (4-5 testers): whitelist via ALLOWED_TELEGRAM_IDS env var
# Fase 3B (50 users): landing page simples + sistema de invite codes
```

**Decisão de onboarding (confirmada):**
- **Agora (4-5 testers):** Whitelist por Telegram ID. Você adiciona os IDs na env var `ALLOWED_TELEGRAM_IDS` no Railway. Usuário faz `/start`, bot checa a lista. Sem página web, sem invite code — direto e zero infra.
- **Depois (até 50 users):** Mini landing page estática (HTML no Railway ou Vercel) com formulário de invite code. Pessoa recebe código, manda pro bot, bot valida e cria conta. Tabela `invite_codes` já estará pronta desde a migration 0009.

**Modificar: `alfred/config.py`** — `allowed_telegram_ids: str = ""`

**Modificar: `alfred/bot/app.py`** — registrar novos handlers

**Beta:** Todos os testers recebem tier `professional` grátis.

---

### Fase 3.4 — RLS Safety Net

**Migration `supabase/migrations/0010_rls_safety_net.sql`:**
```sql
-- Função para setar contexto do usuário na sessão
CREATE OR REPLACE FUNCTION set_request_user(p_user_id UUID)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
    PERFORM set_config('app.current_user_id', p_user_id::text, true);
END;
$$;

-- Dropar policies antigas (auth.uid() que nunca funcionaram)
DROP POLICY IF EXISTS "users_self" ON users;
DROP POLICY IF EXISTS "contacts_owner" ON contacts;
-- ... (todas as 8 policies)

-- Recriar com session variable
CREATE POLICY "contacts_owner_v2" ON contacts
    FOR ALL USING (user_id::text = current_setting('app.current_user_id', true))
    WITH CHECK (user_id::text = current_setting('app.current_user_id', true));
-- ... (todas as tabelas)
```

**Nota:** Com `service_role`, o RLS continua bypassado. As policies são **documentação viva** e entram em vigor quando migrarmos para `anon` key + frontend web (Fase 3.5).

---

## Cronograma de Execução

```
Semana 1:
  [3.0 Segurança]  ║  [3.1 Usage Tracking]
         │                      │
Semana 2:                       ▼
  [3.4 RLS]        [3.2 Tiers + Limites]  ║  [3.3 Acesso]
                            │                     │
Semana 3:                   ▼                     ▼
                   [3.5 Admin Monitoring]
```

**Esforço total: 5-7 dias de desenvolvimento.**

---

## Estimativa de Custos (Mensal, 50 Usuários)

### Premissas
- Média: 8 mensagens/usuário/dia (240/mês)
- Cada mensagem: 1 router call (Haiku) + 1-3 turns de agente (Sonnet com cache)
- 1 nudge/dia por usuário, 1 digest/semana

### Custo por Mensagem
| Componente | Tokens | Custo |
|---|---|---|
| Router (Haiku) | 300 in + 30 out | $0.00036 |
| Agente (Sonnet, cached) | ~600 cache_read + 400 input + 500 output | $0.0079 |
| Embedding (Voyage, 50% msgs) | 100 tokens | $0.000006 |
| **Total/mensagem** | | **~$0.0083** |

### Custo Mensal por Componente
| Serviço | Plano | Custo | Notas |
|---|---|---|---|
| Railway | Hobby | $5-8/mês | Single service, baixo CPU |
| Supabase | Free | $0 | 50 users ~50MB (limite 500MB) |
| Anthropic API | Pay-as-you-go | ~$112/mês | 50 users x $2.23 (msgs + nudges) |
| Voyage AI | Pay-as-you-go | ~$2/mês | ~6000 embeddings |
| Groq (Whisper) | Free | $0 | Voice no tier pago apenas |
| **TOTAL** | | **~R$620/mês** | (~$122 USD) |

**Custo médio por usuário: ~R$12.40/mês ($2.44 USD)**

---

## 4 Opções de Pricing (Brasil, BRL)

### Opção 1: Gratis
| | |
|---|---|
| **Preço** | R$0/mês |
| **Contatos** | 25 |
| **Mensagens/dia** | 15 |
| **Memórias** | 100 |
| **Nudges ativos** | 5 |
| **Voz** | Não |
| **Digest semanal** | Sim |
| **Custo de servir** | ~R$10/mês |
| **Objetivo** | Trial, conversão |

### Opção 2: Pessoal
| | |
|---|---|
| **Preço** | R$29,90/mês |
| **Contatos** | 100 |
| **Mensagens/dia** | 50 |
| **Memórias** | 500 |
| **Nudges ativos** | 20 |
| **Voz** | Sim |
| **Digest** | 2x/semana |
| **Custo de servir** | ~R$15/mês |
| **Margem** | ~50% |
| **Objetivo** | Profissional individual |

### Opção 3: Profissional
| | |
|---|---|
| **Preço** | R$69,90/mês |
| **Contatos** | 300 |
| **Mensagens/dia** | 100 |
| **Memórias** | 2.000 |
| **Nudges ativos** | 50 |
| **Voz** | Sim |
| **Cadência personalizada** | Sim |
| **Custo de servir** | ~R$30/mês |
| **Margem** | ~57% |
| **Objetivo** | Vendedores, networkers |

### Opção 4: Empresarial
| | |
|---|---|
| **Preço** | R$149,90/mês |
| **Contatos** | 1.000 |
| **Mensagens/dia** | 250 |
| **Memórias** | 10.000 |
| **Nudges ativos** | 100 |
| **Voz** | Sim |
| **Suporte prioritário** | Sim |
| **Custo de servir** | ~R$80/mês |
| **Margem** | ~47% |
| **Objetivo** | Agências, alta demanda |

**Beta:** Testers recebem tier Profissional grátis. Quando billing começar, 3 meses de Pessoal free.

---

## Todos os Arquivos Impactados

### Novos
- `alfred/services/access.py` — controle de acesso (whitelist, invite codes)
- `alfred/services/limits.py` — configuração de tiers e enforcement
- `alfred/bot/signing.py` — HMAC para callbacks
- `alfred/bot/admin_handlers.py` — comandos admin no Telegram
- `supabase/migrations/0009_multi_tenant_users.sql`
- `supabase/migrations/0010_rls_safety_net.sql`
- `tests/test_signing.py`
- `tests/test_limits.py`
- `tests/test_access.py`

### Modificados
- `alfred/services/nudges.py` — `user_id` em `handle_nudge_action()`
- `alfred/services/usage.py` — spend per-user
- `alfred/services/contacts.py` — gate de contagem
- `alfred/services/memories.py` — gate de contagem
- `alfred/bot/handlers.py` — access gate, HMAC, user verification em callbacks
- `alfred/bot/keyboards.py` — HMAC signing em todo callback_data
- `alfred/bot/app.py` — registrar novos handlers
- `alfred/agent/orchestrator.py` — `check_limits()` antes de `run_agent()`
- `alfred/config.py` — `allowed_telegram_ids`
- `alfred/db/types.py` — `UserRow` com novos campos
- `alfred/main.py` — admin stats, job endpoint hardening
- `.env.example` — novas env vars

---

## Verificação (End-to-End)

1. **Testes unitários**: `pytest tests/ -x` — todos passam
2. **Segurança**: Testar que usuário A não consegue agir em nudge do usuário B
3. **Limites**: Criar 2 users com tiers diferentes, verificar que limites aplicam
4. **Onboarding**: User novo sem convite recebe mensagem de beta fechado
5. **Callbacks**: Manipular callback_data manualmente → deve rejeitar (HMAC inválido)
6. **Deploy**: Railway com novas env vars, migration via Supabase CLI
7. **Teste manual**: 2 contas no Telegram, cada uma criando contatos — dados isolados
