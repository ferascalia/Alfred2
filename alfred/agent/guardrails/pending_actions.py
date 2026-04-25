"""Pending-actions guardrail — detects mentioned but unexecuted tools."""

import re
from datetime import datetime

import structlog
from dateparser.search import search_dates

from alfred.agent.context import BRT

log = structlog.get_logger()

# Verbos que indicam que o usuário falou/encontrou/interagiu com alguém
_INTERACTION_PATTERNS = [
    r"\bfalei\b", r"\bfalamos\b", r"\bconvers(ei|amos|ando)\b",
    r"\bencontr(ei|amos|ou)\b", r"\bligu(ei|ou)\b", r"\balmo(c|ç)(ei|amos)\b",
    r"\bjant(ei|amos)\b", r"\bvi\s+(o|a|ele|ela)\b", r"\breun(i|imos)\b",
    r"\bmandou\b", r"\bmandei\b", r"\bme\s+ligou\b", r"\bme\s+chamou\b",
    r"\btive\s+(uma\s+)?reuni(ã|a)o\b", r"\bteve\s+(uma\s+)?reuni(ã|a)o\b",
    r"\bacabei\s+de\s+(falar|conversar|sair)\b",
    r"\b(tava|estava)\s+(conversando|falando)\b",
    r"\bme\s+respondeu\b",
    r"\bme\s+passou\s+(mensagem|recado|(á|a)udio)\b",
    r"\bmandou\s+(mensagem|(á|a)udio|recado)\b",
    r"\bmandei\s+(mensagem|(á|a)udio|recado)\b",
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

_ACTION_VERBS = r"(marca|agenda|programa|reagenda|coloca|bota|põe|salva)"
_FOLLOWUP_FALLBACK_PATTERNS = [
    r"\bme\s+lembr(a|e|ar)\s+d[eao]\b",
    rf"\b{_ACTION_VERBS}\b.{{0,40}}\bfollow[\s-]?up\b",
    rf"\b{_ACTION_VERBS}\b.{{0,40}}\bdia\s+\d{{1,2}}\b",
    rf"\b{_ACTION_VERBS}\b.{{0,40}}\b(semana|m(ê|e)s|ano)\s+que\s+vem\b",
    rf"\b{_ACTION_VERBS}\b.{{0,40}}\bpr(ó|o)xim(a|o)\s+(semana|m(ê|e)s|ano)\b",
    r"\bdaqui\s+a\s+(uma|duas|tr(ê|e)s|quatro|cinco|seis|\d+)\s+(dias?|semanas?|meses|m(ê|e)s)\b",
    rf"\b{_ACTION_VERBS}\b.{{0,30}}\bdepois\s+de\s+amanh(ã|a)\b",
]

_QUERY_PATTERNS = [
    r"\bmostr(a|e|ar)\b",
    r"\blist(a|e|ar)\b",
    r"\bquais\b",
    r"\bquantos?\b",
    r"\bver\s+(os?|as?|meus?|minhas?)\b",
    r"\bme\s+mostr(a|e)\b",
]


def detect_future_dates(user_message: str) -> list[tuple[str, datetime]]:
    """Usa dateparser para extrair datas futuras da mensagem. 100% determinístico."""
    now = datetime.now(BRT)
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


def detect_pending_actions(user_message: str, tools_called: set[str]) -> list[str]:
    """Retorna lista de lembretes para ferramentas esperadas mas não chamadas."""
    msg = user_message.lower()
    missing: list[str] = []

    is_query = any(re.search(p, msg) for p in _QUERY_PATTERNS)

    has_interaction = any(re.search(p, msg) for p in _INTERACTION_PATTERNS)
    has_cadence = any(re.search(p, msg) for p in _CADENCE_PATTERNS)
    future_dates = detect_future_dates(user_message)
    has_followup_fallback = any(re.search(p, msg) for p in _FOLLOWUP_FALLBACK_PATTERNS)
    has_followup = bool(future_dates) or has_followup_fallback

    if has_interaction and "log_interaction" not in tools_called:
        missing.append(
            "• `log_interaction` — você mencionou ter falado/encontrado/conversado com a pessoa, "
            "mas não registrou a interação."
        )

    scheduled = (
        "set_follow_up" in tools_called
        or "set_cadence" in tools_called
        or "list_follow_ups" in tools_called
    )
    if has_cadence and not scheduled and not is_query:
        missing.append(
            "• `set_cadence` — você pediu cadência recorrente mas não configurou."
        )
    elif has_followup and not scheduled and not is_query:
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
