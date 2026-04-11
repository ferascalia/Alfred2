# Alfred 🎩

**Agente de Relacionamento de IA** — mantém, aprofunda e não deixa seus relacionamentos caírem no esquecimento.

> *"O assistente que você contrataria se pudesse pagar alguém para lembrar de tudo sobre todos que importam."*

---

## Setup (para o usuário)

Você só precisa fazer 3 coisas. Claude Code cuida do resto.

### 1. Criar as contas e gerar as chaves

Siga cada link e gere/copie a chave quando solicitado pelo Claude Code:

| Serviço | O que fazer |
|---|---|
| [Telegram BotFather](https://t.me/BotFather) | Enviar `/newbot`, anotar o token |
| [Supabase](https://supabase.com) | Criar conta → New Project → copiar URL + `service_role` key |
| [Anthropic](https://console.anthropic.com) | API Keys → Create Key |
| [Voyage AI](https://voyageai.com) | Sign up → API Keys |
| [Railway](https://railway.app) | Account Settings → Tokens → New Token |

### 2. Criar o projeto no Railway

1. Acesse [railway.app](https://railway.app)
2. New Project → Deploy from GitHub repo → selecione `ferascalia/Alfred2`
3. Copie a URL pública gerada (ex: `https://alfred-production.up.railway.app`)

### 3. Configurar variáveis de ambiente no Railway

No Railway dashboard → seu projeto → Variables, adicione cada variável do `.env.example`.

---

## Verificação

Após o deploy:

```bash
curl https://seu-app.up.railway.app/healthz
# → {"status":"ok"}
```

Abra o Telegram, encontre seu bot e envie `/start`.

---

## Comandos disponíveis

| Comando | O que faz |
|---|---|
| `/start` | Apresentação e boas-vindas |
| Mensagem livre | Conversa com o Alfred (adiciona contatos, memórias, etc.) |

*Mais comandos chegam na Fase 1.*

---

## Para o Claude Code

Ver `CLAUDE.md` para decisões de arquitetura e regras do projeto.
