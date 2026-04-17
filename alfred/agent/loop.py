"""Agent loop with tool use."""
import re
from datetime import datetime, timedelta, timezone

import structlog
from anthropic import APIConnectionError, APIStatusError, RateLimitError
from anthropic.types import MessageParam, TextBlock, ToolResultBlockParam, ToolUseBlock
from dateparser.search import search_dates

from alfred.agent.client import MAX_TOKENS, MODEL, get_anthropic
from alfred.agent.prompts import SYSTEM_PROMPT
from alfred.agent.tools import TOOL_SCHEMAS, dispatch_tool
from alfred.db.client import get_db

log = structlog.get_logger()


# ───────────────────────────────────────────────────────────────
# Guardrail determinístico — detecta ações pendentes não executadas
# ───────────────────────────────────────────────────────────────

# Verbos que indicam que o usuário falou/encontrou/interagiu com alguém
_INTERACTION_PATTERNS = [
    r"\bfalei\b", r"\bfalamos\b", r"\bconvers(ei|amos|ando)\b",
    r"\bencontr(ei|amos|ou)\b", r"\bligu(ei|ou)\b", r"\balmo(c|ç)(ei|amos)\b",
    r"\bjant(ei|amos)\b", r"\bvi\s+(o|a|ele|ela)\b", r"\breun(i|imos)\b",
    r"\bmandou\b", r"\bmandei\b", r"\bme\s+ligou\b", r"\bme\s+chamou\b",
    # Reunião no passado
    r"\btive\s+(uma\s+)?reuni(ã|a)o\b", r"\bteve\s+(uma\s+)?reuni(ã|a)o\b",
    r"\bacabei\s+de\s+(falar|conversar|sair)\b",
    r"\b(tava|estava)\s+(conversando|falando)\b",
    # Mensagens trocadas
    r"\bme\s+respondeu\b",
    r"\bme\s+passou\s+(mensagem|recado|(á|a)udio)\b",
    r"\bmandou\s+(mensagem|(á|a)udio|recado)\b",
    r"\bmandei\s+(mensagem|(á|a)udio|recado)\b",
    # Encontros presenciais
    r"\btomei\s+(um\s+)?(caf(é|e)|drink)\s+com\b",
    r"\bcaf(é|e)\s+com\b",
    r"\bpassei\s+(no|na|pelo|pela)\b",
]

# Patterns para cadência recorrente
_CADENCE_PATTERNS = [
    r"\btoda\s+(segunda|ter(ç|c)a|quarta|quinta|sexta|s(á|a)bado|domingo)",
    r"\ba\s+cada\s+\d+\s+dias?\b", r"\bde\s+\d+\s+em\s+\d+\s+dias?\b",
    r"\bsemanalmente\b", r"\bmensalmente\b",
    r"\btoda\s+(semana|quinzena|m(ê|e)s)\b",
    r"\bquinzenalmente\b",
    r"\b(uma|duas|tr(ê|e)s)\s+vezes\s+por\s+(semana|m(ê|e)s)\b",
]


# Fallback patterns para intenção de follow-up que o dateparser NÃO cobre em pt-BR.
# Quando algum desses dispara e o dateparser não extraiu nada, forçamos set_follow_up
# mas sem data pré-calculada — o Claude precisa resolver.
_FOLLOWUP_FALLBACK_PATTERNS = [
    r"\bme\s+lembr(a|e|ar)\b",
    r"\bfollow[\s-]?up\b",
    r"\bdia\s+\d{1,2}\b",                        # "dia 20"
    r"\bsemana\s+que\s+vem\b",
    r"\bm(ê|e)s\s+que\s+vem\b",
    r"\bano\s+que\s+vem\b",
    r"\bdaqui\s+a\s+(uma|duas|tr(ê|e)s|quatro|cinco|seis)\s+(dias?|semanas?|meses|m(ê|e)s)\b",
    r"\bem\s+(uma|duas|tr(ê|e)s|quatro|cinco|seis)\s+(dias?|semanas?|meses|m(ê|e)s)\b",
    r"\bpr(ó|o)xim(a|o)\s+(semana|m(ê|e)s|ano)\b",
    r"\bdepois\s+de\s+amanh(ã|a)\b",
]

_BRT = timezone(timedelta(hours=-3))

# ───────────────────────────────────────────────────────────────
# Date-confirmation prompt detector
# Claude é instruído no system prompt a iniciar qualquer proposta de data
# com a palavra literal "Confirmando:" seguida de pelo menos uma data numérica.
# Quando o turno termina assim, pulamos ambos guardrails (pending-actions e
# veracidade) porque a pausa é legítima — não é alucinação.
# ───────────────────────────────────────────────────────────────
_DATE_CONFIRM_PREFIX = re.compile(r"^\s*confirmando\s*:", re.IGNORECASE)
_CONFIRMATION_APPROVED = "[CONFIRMAÇÃO APROVADA]"
_DATE_NUMERIC = re.compile(
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b"
)


def _is_date_confirmation_prompt(response_text: str) -> bool:
    """True quando Claude está propondo uma data para confirmação do usuário.

    Requer DOIS sinais determinísticos simultâneos:
    - Prefixo literal "Confirmando:" no início de qualquer linha/parágrafo
      (Claude pode criar contatos primeiro e só depois propor a confirmação)
    - Pelo menos uma data numérica (DD/MM, DD/MM/AAAA ou YYYY-MM-DD) no corpo
    """
    if not response_text:
        return False
    # Checa se alguma linha começa com "Confirmando:"
    has_prefix = any(
        _DATE_CONFIRM_PREFIX.match(line)
        for line in response_text.split("\n")
    )
    if not has_prefix:
        return False
    if not _DATE_NUMERIC.search(response_text):
        return False
    return True


def _detect_future_dates(user_message: str) -> list[tuple[str, datetime]]:
    """Usa dateparser para extrair datas futuras da mensagem. 100% determinístico."""
    now = datetime.now(_BRT)
    try:
        hits = search_dates(
            user_message,
            languages=["pt"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": now.replace(tzinfo=None),
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        ) or []
    except Exception:
        log.exception("dateparser.search_dates_failed", message=user_message)
        return []

    today = now.date()
    return [(snippet, dt) for (snippet, dt) in hits if dt.date() > today]


def _detect_pending_actions(user_message: str, tools_called: set[str]) -> list[str]:
    """Retorna lista de lembretes para ferramentas esperadas mas não chamadas."""
    msg = user_message.lower()
    missing: list[str] = []

    has_interaction = any(re.search(p, msg) for p in _INTERACTION_PATTERNS)
    has_cadence = any(re.search(p, msg) for p in _CADENCE_PATTERNS)
    future_dates = _detect_future_dates(user_message)
    has_followup_fallback = any(re.search(p, msg) for p in _FOLLOWUP_FALLBACK_PATTERNS)
    has_followup = bool(future_dates) or has_followup_fallback

    if has_interaction and "log_interaction" not in tools_called:
        missing.append(
            "• `log_interaction` — você mencionou ter falado/encontrado/conversado com a pessoa, "
            "mas não registrou a interação."
        )

    # Cadência tem prioridade sobre follow-up pontual
    scheduled = "set_follow_up" in tools_called or "set_cadence" in tools_called
    if has_cadence and not scheduled:
        missing.append(
            "• `set_cadence` — você pediu cadência recorrente mas não configurou."
        )
    elif has_followup and not scheduled:
        if future_dates:
            snippet, dt = future_dates[0]
            date_iso = dt.date().isoformat()
            missing.append(
                f"• `set_follow_up` — você mencionou '{snippet.strip()}' "
                f"(interpretado como {date_iso}) mas não agendou. "
                f"Chame set_follow_up com date='{date_iso}'."
            )
        else:
            missing.append(
                "• `set_follow_up` — você mencionou um prazo, data futura ou 'me lembra' "
                "mas não agendou o follow-up. Calcule a data absoluta (YYYY-MM-DD) a partir de hoje."
            )

    return missing


# ───────────────────────────────────────────────────────────────
# Validador de veracidade da RESPOSTA — cruza com fonte confiável (DB)
# ───────────────────────────────────────────────────────────────

# Se Claude usa essas frases, ele está afirmando ter executado a tool correspondente.
# Se a tool não foi chamada neste turno, é alucinação.
_CLAIM_PATTERNS: dict[str, list[str]] = {
    "create_contact": [
        r"\b(cadastrei|criei|adicionei|registrei)\s+(o\s+|a\s+)?(contato|pessoa)\b",
        r"\bcontato\s+(criado|cadastrado|adicionado)\b",
        r"\bj(á|a)\s+(est(á|a)|foi)\s+(cadastrad[oa]|adicionad[oa]|criad[oa])\b",
        r"\badicionei\s+(à|a)\s+(sua\s+)?(lista|base)\b",
    ],
    "log_interaction": [
        r"\b(registrei|anotei|salvei|gravei)\s+(a\s+)?(intera(ç|c)(ã|a)o|conversa|encontro|reuni(ã|a)o)\b",
        r"\bintera(ç|c)(ã|a)o\s+(registrada|gravada|anotada)\b",
    ],
    "set_follow_up": [
        r"\b(marquei|agendei|programei|criei)\s+(o\s+|um\s+)?follow[\s-]?up\b",
        r"\bfollow[\s-]?up\s+(marcad[oa]|agendad[oa]|criad[oa])\b",
        r"\blembrete\s+(criad[oa]|marcad[oa]|agendad[oa])\b",
        r"\bte\s+(lembro|lembrarei|aviso|avisarei)\s+(em|no\s+dia|na\s+|amanh(ã|a)|quando)",
    ],
    "set_cadence": [
        r"\bcad(ê|e)ncia\s+(definida|configurada|criada|atualizada)\b",
        r"\bvou\s+(te\s+)?lembrar\s+tod[oa]s?\s+",
    ],
    "add_memory": [
        r"\b(adicionei|salvei|registrei|anotei)\s+(a\s+|uma\s+|essa\s+|esta\s+)?mem(ó|o)ria\b",
        r"\bmem(ó|o)ria\s+(adicionada|salva|registrada|gravada)\b",
    ],
    "list_follow_ups": [
        r"\bseus\s+follow[\s-]?ups?\s+(marcad[oa]s?|agendad[oa]s?|s(ã|a)o)\b",
        r"\bfollow[\s-]?ups?\s+(marcad[oa]s?|agendad[oa]s?)\s+para\b",
        r"\baqui\s+(est(ã|a)o|v(ã|a)o)\s+(os\s+)?seus\s+follow[\s-]?ups?\b",
        r"\bseus\s+(lembretes|compromissos)\s+(marcad[oa]s?|agendad[oa]s?|s(ã|a)o)\b",
        r"\b(voc(ê|e))\s+tem\s+(os\s+seguintes\s+)?follow[\s-]?ups?\b",
    ],
}

_NAME_RE = re.compile(
    r"\b([A-ZÀ-Úa-zà-ú]*[A-ZÀ-Ú][a-zà-ú]{2,}"
    r"(?:\s+(?:de\s+|da\s+|do\s+|dos\s+|das\s+|e\s+)?[A-ZÀ-Ú][a-zà-ú]+)*)\b"
)

# Palavras Title Case que NÃO são nomes de contato — evita falso positivo
_NAME_STOPWORDS: set[str] = {
    "Alfred", "Claude", "Anthropic", "Telegram", "WhatsApp",
    "Sim", "Não", "Nao", "Ok", "Okay", "Olá", "Ola", "Oi", "Feito", "Pronto", "Certo",
    "Obrigado", "Obrigada", "Opa", "Eba", "Entendi", "Beleza",
    "Segunda", "Terça", "Terca", "Quarta", "Quinta", "Sexta", "Sábado", "Sabado", "Domingo",
    "Janeiro", "Fevereiro", "Março", "Marco", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
    "Hoje", "Amanhã", "Amanha", "Ontem",
    "Cadência", "Cadencia", "Contato", "Contatos", "Memória", "Memoria", "Memórias", "Memorias",
    "Interação", "Interacao", "Interações", "Interacoes",
    "Follow", "FollowUp", "Lembrete", "Lembretes",
    "BRT",
    # Verbos em 1ª pessoa do singular — começo de frase típico do Alfred
    "Cadastrei", "Criei", "Adicionei", "Registrei", "Salvei", "Gravei", "Anotei",
    "Marquei", "Agendei", "Programei", "Atualizei", "Defini", "Configurei",
    "Falei", "Encontrei", "Liguei", "Conversei", "Vi", "Tive", "Arquivei", "Mesclei",
    "Preciso", "Quero", "Quer", "Vou", "Devo", "Posso", "Consigo", "Acho", "Sei", "Tenho",
    "Entendi", "Procurei", "Busquei", "Verifiquei", "Confirmei",
    # Verbos 3ª pessoa comuns
    "Feito", "Pronto", "Prontinho",
    # Pronomes/conectores comuns em início de frase
    "Ele", "Ela", "Eles", "Elas", "Isso", "Isto", "Aquilo", "Essa", "Esse", "Este", "Esta",
    "Aqui", "Lá", "La", "Ali", "Agora", "Depois", "Antes", "Então", "Entao",
    "Mas", "Porém", "Porem", "Contudo", "Portanto",
    # Termos de empresa/organização — não são nomes de contato
    "Banco", "Mercedes", "Inter", "Itaú", "Itau", "Bradesco", "Santander",
    "Nubank", "Brasil", "Google", "Apple", "Microsoft", "Amazon",
    "Igreja", "Empresa", "Grupo", "Instituto", "Fundação", "Fundacao",
    "Associação", "Associacao", "Companhia", "Ltda", "Eireli",
    "Capital", "Partners", "Ventures", "Labs", "Tech", "Digital",
}


def _extract_claimed_tools(text: str) -> set[str]:
    text_l = text.lower()
    claimed: set[str] = set()
    for tool, patterns in _CLAIM_PATTERNS.items():
        if any(re.search(p, text_l) for p in patterns):
            claimed.add(tool)
    return claimed


def _extract_names(text: str) -> set[str]:
    """Extrai candidatos a nome próprio (Title Case) do texto, filtrando stopwords.
    Ignora a primeira palavra capitalizada de cada sentença (início de frase)."""
    names: set[str] = set()
    # Split por pontuação de fim de sentença + newline
    sentences = re.split(r"[.!?\n]+", text)
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        matches = _NAME_RE.findall(sent)
        if not matches:
            continue
        # O primeiro match pode ser o início da frase → só aceita se NÃO for stopword.
        # Stopwords no início são ignoradas; não-stopwords no início passam
        # (pode ser um nome próprio iniciando a frase, ex: "Daniel foi registrado").
        for m in matches:
            if m in _NAME_STOPWORDS:
                continue
            if len(m) < 3:
                continue
            names.add(m)
    return names


def _name_matches(a: str, b: str) -> bool:
    a_l, b_l = a.lower(), b.lower()
    if a_l == b_l:
        return True
    # Match parcial: primeiro nome ou substring
    a_tokens = set(a_l.split())
    b_tokens = set(b_l.split())
    return bool(a_tokens & b_tokens)


async def _validate_response_truthfulness(
    user_id: str,
    final_text: str,
    tool_calls_log: list[tuple[str, dict]],
) -> list[str]:
    """Cruza o texto final com o que realmente foi executado + fonte confiável (DB)."""
    problems: list[str] = []
    tools_called = {name for name, _ in tool_calls_log}

    # ── Validador 1: afirmação de ação sem tool call correspondente ──
    claimed = _extract_claimed_tools(final_text)
    for tool in claimed:
        if tool not in tools_called:
            problems.append(
                f"• Você afirmou ter executado `{tool}` mas NÃO chamou essa ferramenta "
                f"neste turno. Chame AGORA ou retire a afirmação."
            )

    # ── Validador 2: nomes mencionados que não existem no DB ──
    names = _extract_names(final_text)
    if names:
        created_names: list[str] = []
        searched_names: list[str] = []
        for tname, tinput in tool_calls_log:
            if tname == "create_contact":
                dn = (tinput.get("display_name") or "").strip()
                if dn:
                    created_names.append(dn)
            elif tname == "list_contacts":
                s = (tinput.get("search") or "").strip()
                if s:
                    searched_names.append(s)

        try:
            db = get_db()
            existing = (
                db.table("contacts")
                .select("display_name")
                .eq("user_id", user_id)
                .eq("status", "active")
                .execute()
            )
            existing_names = [c["display_name"] for c in (existing.data or [])]
        except Exception:
            log.exception("validator.db_lookup_failed")
            existing_names = []

        for name in names:
            in_db = any(_name_matches(name, e) for e in existing_names)
            was_created = any(_name_matches(name, c) for c in created_names)
            was_searched = any(_name_matches(name, s) for s in searched_names)

            if in_db or was_created:
                continue
            if was_searched:
                # Claude buscou, não achou, não criou → está confirmando algo que não existe
                problems.append(
                    f"• Você mencionou '{name}' mas `list_contacts` mostrou que essa pessoa "
                    f"NÃO existe e você não chamou `create_contact`. Não confirme o que não fez."
                )
                continue
            problems.append(
                f"• Você mencionou '{name}' na resposta, mas essa pessoa não existe no banco "
                f"e você não chamou `list_contacts` nem `create_contact` neste turno. "
                f"Nunca invente contatos — chame `list_contacts` para verificar primeiro."
            )

    return problems


async def _alert_owner(telegram_id: int, message: str) -> None:
    """Send an urgent alert to the user via Telegram."""
    try:
        from telegram import Bot
        from alfred.config import settings
        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(chat_id=telegram_id, text=message, parse_mode="Markdown")
    except Exception:
        log.exception("alert.failed", telegram_id=telegram_id)


async def _get_or_create_user(telegram_id: int, user_name: str) -> str:
    """Return the internal user UUID for a Telegram user."""
    db = get_db()
    result = (
        db.table("users")
        .upsert(
            {
                "telegram_id": telegram_id,
                "name": user_name,
                "timezone": "America/Sao_Paulo",
                "locale": "pt-BR",
            },
            on_conflict="telegram_id",
        )
        .execute()
    )
    return result.data[0]["id"]


async def _load_history(user_id: str, limit: int = 20) -> list[MessageParam]:
    """Load recent conversation messages from DB."""
    db = get_db()

    conv_result = (
        db.table("conversations")
        .select("id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not conv_result.data:
        return []

    conv_id = conv_result.data[0]["id"]
    msgs_result = (
        db.table("messages")
        .select("role, content")
        .eq("conversation_id", conv_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    messages: list[MessageParam] = []
    for row in reversed(msgs_result.data):
        messages.append({"role": row["role"], "content": row["content"]})  # type: ignore[typeddict-item]
    return messages


async def _save_message(user_id: str, role: str, content: object) -> None:
    db = get_db()

    # Get or create conversation
    conv_result = (
        db.table("conversations")
        .select("id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if conv_result.data:
        conv_id = conv_result.data[0]["id"]
        db.table("conversations").update({"last_message_at": "now()"}).eq("id", conv_id).execute()
    else:
        new_conv = db.table("conversations").insert({"user_id": user_id, "telegram_chat_id": 0}).execute()
        conv_id = new_conv.data[0]["id"]

    db.table("messages").insert({
        "conversation_id": conv_id,
        "role": role,
        "content": content,
    }).execute()


async def run_agent(telegram_id: int, user_name: str, message: str) -> str:
    """Run one agent turn. Returns the text response."""
    from datetime import datetime, timezone, timedelta
    brt = timezone(timedelta(hours=-3))
    now = datetime.now(brt)
    current_date_str = now.strftime("%Y-%m-%d (%A, %H:%M BRT)")  # ex: "2026-04-12 (Sunday, 08:30 BRT)"
    system_prompt = SYSTEM_PROMPT + f"\n\n## Data e hora atual\nHoje é {current_date_str}. Use sempre esta data/hora como referência ao registrar interações (happened_at) ou calcular follow-ups. Nunca use datas do passado para happened_at — use a data de hoje salvo o usuário dizer explicitamente outra."

    user_id = await _get_or_create_user(telegram_id, user_name)
    history = await _load_history(user_id)

    # Append new user message
    history.append({"role": "user", "content": message})
    await _save_message(user_id, "user", message)

    client = get_anthropic()
    messages = list(history)

    # Pula guardrail de pending_actions quando o turno é resposta a uma confirmação
    # (botão ✅ envia "[CONFIRMAÇÃO APROVADA]" ou último assistant msg era "Confirmando:")
    skip_pending_guardrail = message.startswith(_CONFIRMATION_APPROVED)
    if not skip_pending_guardrail:
        for m in reversed(history[:-1]):  # exclui a msg atual que acabamos de appendar
            if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                skip_pending_guardrail = _is_date_confirmation_prompt(m["content"])
                break

    # Tracks every tool name executed neste turno — usado pelo guardrail
    tools_called_this_turn: set[str] = set()
    # Log completo (nome + input) — usado pelo validador de veracidade
    tool_calls_log: list[tuple[str, dict]] = []
    # Quantas vezes o guardrail reinjetou lembrete (evita loop infinito).
    # Budget compartilhado entre guardrail de input e validador de output.
    guardrail_retries = 0
    MAX_GUARDRAIL_RETRIES = 2
    # Quando True, pula o validador de veracidade (date-tools foram bloqueadas,
    # então a resposta é intermediária e não deve ser julgada como final)
    date_tools_blocked = False
    # Quando True, força tool_choice=any no próximo round para quebrar
    # alucinações em que Claude insiste em emitir texto sem chamar ferramentas
    force_tool_use_next_round = False

    # Agentic loop — keep going until we get a stop_turn with no tool calls
    for _turn in range(10):  # max 10 tool rounds
        try:
            create_kwargs: dict = {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "tools": TOOL_SCHEMAS,
                "messages": messages,
            }
            if force_tool_use_next_round:
                create_kwargs["tool_choice"] = {"type": "any"}
                force_tool_use_next_round = False
            response = await client.messages.create(**create_kwargs)
        except RateLimitError:
            log.warning("anthropic.rate_limit")
            return "Estou sobrecarregado no momento, tente em alguns minutos. 🔄"
        except APIStatusError as exc:
            log.error("anthropic.api_error", status=exc.status_code)
            if exc.status_code == 402:
                await _alert_owner(
                    telegram_id,
                    "⚠️ *Alerta Alfred*: Créditos da Anthropic esgotados. O assistente está fora do ar até você recarregar em https://console.anthropic.com.",
                )
                return "Meus créditos acabaram. Já te avisei por aqui — recarrega lá no console da Anthropic para eu voltar. 💳"
            return "Ocorreu um erro no servidor, tente novamente. 🛠️"
        except APIConnectionError:
            log.error("anthropic.connection_error")
            return "Não consegui conectar ao servidor, tente novamente. 🔌"

        log.info(
            "agent.response",
            stop_reason=response.stop_reason,
            usage=response.usage.model_dump(),
        )

        # Collect tool calls from this response
        tool_calls = [b for b in response.content if isinstance(b, ToolUseBlock)]
        text_blocks = [b for b in response.content if isinstance(b, TextBlock)]

        if response.stop_reason == "end_turn" or not tool_calls:
            # ───── Bypass legítimo: proposta de confirmação de data ─────
            # Se Claude está pausando para confirmar uma data com o usuário
            # (formato "Confirmando: ... DD/MM/AAAA ...?"), pulamos guardrail
            # e validador. Esse é o único caso em que a ausência de tool call
            # não é alucinação — é o fluxo propor→confirmar→executar.
            preview_text = "\n".join(b.text for b in text_blocks).strip()
            if _is_date_confirmation_prompt(preview_text):
                log.info(
                    "guardrail.date_confirmation_bypass",
                    preview=preview_text[:240],
                    tools_called=list(tools_called_this_turn),
                )
                await _save_message(user_id, "assistant", preview_text)
                return preview_text

            # ───── Guardrail: verifica ferramentas pendentes ─────
            missing = (
                _detect_pending_actions(message, tools_called_this_turn)
                if not skip_pending_guardrail
                else []
            )
            if missing and guardrail_retries < MAX_GUARDRAIL_RETRIES:
                guardrail_retries += 1
                log.warning(
                    "guardrail.pending_actions",
                    missing=missing,
                    tools_called=list(tools_called_this_turn),
                    retry=guardrail_retries,
                )
                reminder_text = (
                    "⚠️ STOP. IGNORE qualquer confirmação anterior no histórico — aquilo pode "
                    "ser alucinação de turno passado. Verifique APENAS o que foi executado "
                    "neste turno atual via ferramentas.\n\n"
                    "Faltam ferramentas a chamar para cumprir a mensagem atual do usuário:\n\n"
                    + "\n".join(missing)
                    + "\n\nExecute essas ferramentas AGORA. Se precisar do contact_id, chame "
                    "list_contacts primeiro. Se o contato não existir, chame create_contact. "
                    "NÃO emita texto final até que todas as ações tenham sido realmente realizadas."
                )
                # Continua o diálogo: injeta a resposta de Claude + correção sintética como user
                messages.append({"role": "assistant", "content": response.content})  # type: ignore[typeddict-item]
                messages.append({"role": "user", "content": reminder_text})
                # Força Claude a chamar uma ferramenta no próximo round —
                # não pode mais escapar emitindo só texto
                force_tool_use_next_round = True
                continue

            # Guardrail esgotou retries mas ainda detecta ferramenta faltando →
            # NUNCA retornar texto alucinado. Responde erro explícito.
            if missing:
                log.error(
                    "guardrail.exhausted",
                    missing=missing,
                    tools_called=list(tools_called_this_turn),
                )
                error_msg = (
                    "Ops, travou aqui e não consegui executar tudo o que você pediu. "
                    "Pode confirmar o que você quer que eu faça? Vou refazer com cuidado. 🙏"
                )
                await _save_message(user_id, "assistant", error_msg)
                return error_msg

            # Final answer (candidato)
            final_text = "\n".join(b.text for b in text_blocks).strip()
            if not final_text:
                final_text = "Feito."

            # ───── Validador de veracidade — cruza texto com DB ─────
            # Pula quando date-tools foram bloqueadas: a resposta é intermediária
            # ("Confirmando:") e não deve ser julgada como resposta final.
            truthfulness_problems = (
                await _validate_response_truthfulness(
                    user_id=user_id,
                    final_text=final_text,
                    tool_calls_log=tool_calls_log,
                )
                if not date_tools_blocked
                else []
            )
            if truthfulness_problems and guardrail_retries < MAX_GUARDRAIL_RETRIES:
                guardrail_retries += 1
                log.warning(
                    "validator.untruthful_response",
                    problems=truthfulness_problems,
                    tools_called=list(tools_called_this_turn),
                    retry=guardrail_retries,
                )
                reminder_text = (
                    "⚠️ STOP. Sua resposta contém afirmações que não correspondem ao que foi "
                    "realmente executado neste turno, ou menciona pessoas que não estão no banco.\n\n"
                    "Problemas detectados:\n\n"
                    + "\n".join(truthfulness_problems)
                    + "\n\nCorrija AGORA: ou execute as ferramentas que faltam, ou reescreva "
                    "a resposta sem inventar fatos. NUNCA confirme algo que você não fez. "
                    "Se não encontrou um contato, diga isso explicitamente e pergunte se deve criar."
                )
                messages.append({"role": "assistant", "content": response.content})  # type: ignore[typeddict-item]
                messages.append({"role": "user", "content": reminder_text})
                force_tool_use_next_round = True
                continue

            if truthfulness_problems:
                # Validador esgotou retries — pede confirmação ao usuário em vez de mentir
                log.error(
                    "validator.exhausted",
                    problems=truthfulness_problems,
                    tools_called=list(tools_called_this_turn),
                )
                error_msg = (
                    "Não consegui validar o que ia te responder — alguma informação não "
                    "bateu com o que está salvo. Pode me confirmar exatamente o que você "
                    "quer que eu faça (quem, quando, o quê)? Vou refazer do zero. 🙏"
                )
                await _save_message(user_id, "assistant", error_msg)
                return error_msg

            # Save assistant message
            await _save_message(user_id, "assistant", final_text)
            return final_text

        # ───── Guardrail: bloqueia tools de data sem confirmação prévia ─────
        _DATE_TOOLS = {"set_follow_up", "log_interaction"}
        date_tools_requested = [tc for tc in tool_calls if tc.name in _DATE_TOOLS]
        if date_tools_requested and not skip_pending_guardrail:
            log.warning(
                "guardrail.date_tool_without_confirmation",
                tools=[tc.name for tc in date_tools_requested],
            )
            # Após bloquear, desativa pending-actions guardrail e truthfulness
            # validator para evitar deadlock (eles exigiriam/julgariam as
            # mesmas tools que bloqueamos).
            skip_pending_guardrail = True
            date_tools_blocked = True

            blocked_results: list[ToolResultBlockParam] = []
            # Extrai as datas que Claude tentou usar para incluir na instrução
            attempted_dates: list[str] = []
            for tc in date_tools_requested:
                inp = dict(tc.input)  # type: ignore[arg-type]
                d = inp.get("date") or inp.get("happened_at") or ""
                if d:
                    attempted_dates.append(d)
            date_hint = ""
            if attempted_dates:
                formatted = ", ".join(attempted_dates)
                date_hint = f" As datas que você calculou ({formatted}) estão corretas — inclua-as no formato DD/MM/AAAA."

            for tool_call in tool_calls:
                if tool_call.name in _DATE_TOOLS:
                    blocked_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": (
                            "BLOQUEADO: esta ferramenta só pode ser chamada DEPOIS que o "
                            "usuário confirmar a data via botão ✅. Responda APENAS com texto "
                            "(sem chamar nenhuma ferramenta) começando com a palavra "
                            "'Confirmando:' seguida das datas no formato DD/MM/AAAA. "
                            "Exemplo: 'Confirmando: follow-up do Fulano para 23/04/2026 (quarta)?'"
                            f"{date_hint} "
                            "NÃO chame esta ferramenta novamente até receber "
                            "'[CONFIRMAÇÃO APROVADA]'."
                        ),
                        "is_error": True,
                    })
                else:
                    tools_called_this_turn.add(tool_call.name)
                    tool_calls_log.append((tool_call.name, dict(tool_call.input)))  # type: ignore[arg-type]
                    try:
                        result = await dispatch_tool(
                            tool_name=tool_call.name,
                            tool_input=dict(tool_call.input),  # type: ignore[arg-type]
                            user_id=user_id,
                        )
                    except Exception as exc:
                        log.exception("tool.error", tool=tool_call.name)
                        result = f"Erro ao executar ferramenta: {exc}"
                    blocked_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": result,
                    })
            messages.append({"role": "assistant", "content": response.content})  # type: ignore[typeddict-item]
            messages.append({"role": "user", "content": blocked_results})  # type: ignore[typeddict-item]
            continue

        # Execute tool calls
        tool_results: list[ToolResultBlockParam] = []
        for tool_call in tool_calls:
            tools_called_this_turn.add(tool_call.name)
            tool_calls_log.append((tool_call.name, dict(tool_call.input)))  # type: ignore[arg-type]
            try:
                result = await dispatch_tool(
                    tool_name=tool_call.name,
                    tool_input=dict(tool_call.input),  # type: ignore[arg-type]
                    user_id=user_id,
                )
            except Exception as exc:
                log.exception("tool.error", tool=tool_call.name)
                result = f"Erro ao executar ferramenta: {exc}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": result,
            })

        # Add assistant turn + tool results to messages
        messages.append({"role": "assistant", "content": response.content})  # type: ignore[typeddict-item]
        messages.append({"role": "user", "content": tool_results})  # type: ignore[typeddict-item]

    return "Não consegui completar a solicitação. Por favor, tente novamente."
