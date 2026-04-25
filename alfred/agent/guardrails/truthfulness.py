"""Truthfulness validator — cross-checks claims vs actual tool calls and DB."""

import re

import structlog

from alfred.db.client import get_db

log = structlog.get_logger()

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
    "Cadastrei", "Criei", "Adicionei", "Registrei", "Salvei", "Gravei", "Anotei",
    "Marquei", "Agendei", "Programei", "Atualizei", "Defini", "Configurei",
    "Falei", "Encontrei", "Liguei", "Conversei", "Vi", "Tive", "Arquivei", "Mesclei",
    "Preciso", "Quero", "Quer", "Vou", "Devo", "Posso", "Consigo", "Acho", "Sei", "Tenho",
    "Entendi", "Procurei", "Busquei", "Verifiquei", "Confirmei",
    "Feito", "Pronto", "Prontinho",
    "Ele", "Ela", "Eles", "Elas", "Isso", "Isto", "Aquilo", "Essa", "Esse", "Este", "Esta",
    "Aqui", "Lá", "La", "Ali", "Agora", "Depois", "Antes", "Então", "Entao",
    "Mas", "Porém", "Porem", "Contudo", "Portanto",
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
    """Extrai candidatos a nome próprio (Title Case) do texto, filtrando stopwords."""
    names: set[str] = set()
    sentences = re.split(r"[.!?\n]+", text)
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        matches = _NAME_RE.findall(sent)
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
    a_tokens = set(a_l.split())
    b_tokens = set(b_l.split())
    return bool(a_tokens & b_tokens)


async def validate_response_truthfulness(
    user_id: str,
    final_text: str,
    tool_calls_log: list[tuple[str, dict]],
) -> list[str]:
    """Cruza o texto final com o que realmente foi executado + fonte confiável (DB)."""
    problems: list[str] = []
    tools_called = {name for name, _ in tool_calls_log}

    claimed = _extract_claimed_tools(final_text)
    for tool in claimed:
        if tool not in tools_called:
            problems.append(
                f"• Você afirmou ter executado `{tool}` mas NÃO chamou essa ferramenta "
                f"neste turno. Chame AGORA ou retire a afirmação."
            )

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
