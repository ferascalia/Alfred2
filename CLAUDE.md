# Alfred — Decisões Vivas do Projeto

**Atualizado por:** Claude Code  
**Repositório:** `ferascalia/Alfred2` (branch `master`)

---

## O que é o Alfred

Agente de Relacionamento de IA com memória persistente. Ajuda o usuário a manter conexões pessoais e profissionais sem deixar ninguém cair no esquecimento. Referência conceitual: [Dex](https://getdex.com/).

**Não é:** CRM, agenda, chatbot genérico.  
**É:** o assistente que você contrataria se pudesse pagar alguém para lembrar de tudo sobre todos que importam.

---

## Stack

| Camada | Escolha |
|---|---|
| Linguagem | Python 3.12 + FastAPI |
| Package manager | `uv` (Astral) |
| Bot Telegram | `python-telegram-bot` v21, modo webhook |
| LLM | Claude Sonnet 4.6 (`claude-sonnet-4-6`) com prompt caching |
| Embeddings | Voyage AI `voyage-3` (1024 dims) |
| Banco | Supabase (Postgres + pgvector + RLS + pg_cron) |
| Hosting | Railway (Hobby $5/mês) |
| CI | GitHub Actions |

---

## Princípios invioláveis (não mudar sem discussão)

1. **Memória é sagrada** — precisa, atribuída, sempre deletável
2. **Sugere, nunca age** — Alfred rascunha; humano envia
3. **Só interrompe com valor real** — zero notificação vazia
4. **Calor humano > automação** — mensagens soam naturais
5. **Privacidade por design** — RLS desde o dia 1, sem fontes externas

---

## Regras estruturais do agente

- `draft_message` existe; `send_message_to_contact` **não existe e nunca vai existir**
- O agente usa `claude-sonnet-4-6` — **um modelo só** (sem DeepSeek, sem fallbacks)
- Prompt caching ativo no system prompt (cache_control: ephemeral)
- Máximo de 10 rounds de tool use por turn (`loop.py`)

---

## Estrutura de arquivos

```
alfred/
├── main.py          — FastAPI app + lifespan (webhook + healthz + /jobs/nudge)
├── config.py        — pydantic-settings (env vars)
├── logging.py       — structlog setup
├── bot/             — PTB handlers, keyboards, Application factory
├── agent/           — Anthropic client, system prompt, tool schemas, agent loop
├── services/        — contacts, memories (Voyage+pgvector), interactions, nudges
├── db/              — Supabase client singleton, TypedDicts
└── jobs/            — nudge worker (process_nudge)
supabase/migrations/ — 0001 schema, 0002 RLS, 0003 pg_cron + pgvector functions
tests/               — pytest unit tests com mocks
```

---

## Deploy

- **Railway**: `uvicorn alfred.main:app --host 0.0.0.0 --port $PORT`
- Health check: `GET /healthz` → `{"status":"ok"}`
- Webhook: `POST /webhook` com header `X-Telegram-Bot-Api-Secret-Token`
- Nudge job: `POST /jobs/nudge` com header `X-Jobs-Secret` + body `{"contact_id":"..."}`

---

## Env vars necessárias

Ver `.env.example` na raiz do projeto.

---

## Decisões que já foram tomadas

- **Python sobre TypeScript** — ecossistema LLM mais maduro
- **Um LLM só (Sonnet 4.6)** — prompt caching cobre o custo; complexidade não vale
- **pg_cron** em vez de Railway cron — transacional, sem infra extra
- **RLS no MVP** — custo zero agora, elimina refactor na Fase 3 (multi-tenant)
- **Voyage sobre OpenAI embeddings** — multilíngue melhor, recomendado pela Anthropic
- **Railway sobre Fly.io** — melhor DX de CLI, Claude Code pode fazer deploy sozinho

---

## Roadmap

- **Fase 0** ✅ Setup + scaffold + /start + /healthz + deploy base
- **Fase 1** — Agent loop + tools + nudges completos
- **Fase 2** — Voz (Groq Whisper), digest semanal, dedup de contatos
- **Fase 3** — SaaS multi-tenant (Supabase Auth + Next.js + Stripe)
- **Fase 4** — WhatsApp, Gmail, Google Calendar
