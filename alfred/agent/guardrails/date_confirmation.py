"""Date-confirmation guardrail — detects 'Confirmando:' proposals."""

import re

_DATE_CONFIRM_PREFIX = re.compile(r"^\s*confirmando\s*:", re.IGNORECASE)
CONFIRMATION_APPROVED = "[CONFIRMAÇÃO APROVADA]"
_DATE_NUMERIC = re.compile(
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b"
)
_SCHEDULING_CHOICE_PREFIX = re.compile(r"^\s*escolha como agendar\s*:", re.IGNORECASE)
_REMINDER_FOLLOWUP_PREFIX = re.compile(r"^\s*lembrete no telegram\s*\??", re.IGNORECASE)


def is_date_confirmation_prompt(response_text: str) -> bool:
    """True quando Claude está propondo uma data para confirmação do usuário.

    Requer DOIS sinais determinísticos simultâneos:
    - Prefixo literal "Confirmando:" no início de qualquer linha/parágrafo
    - Pelo menos uma data numérica (DD/MM, DD/MM/AAAA ou YYYY-MM-DD) no corpo
    """
    if not response_text:
        return False
    has_prefix = any(
        _DATE_CONFIRM_PREFIX.match(line)
        for line in response_text.split("\n")
    )
    if not has_prefix:
        return False
    if not _DATE_NUMERIC.search(response_text):
        return False
    return True


def is_scheduling_disambiguation(response_text: str) -> bool:
    """True when the agent is asking the user to choose between Calendar and Reminder."""
    if not response_text:
        return False
    return any(
        _SCHEDULING_CHOICE_PREFIX.match(line)
        for line in response_text.split("\n")
    )


def is_reminder_followup_prompt(response_text: str) -> bool:
    """True when the agent is asking if the user also wants a Telegram reminder."""
    if not response_text:
        return False
    return any(
        _REMINDER_FOLLOWUP_PREFIX.match(line)
        for line in response_text.split("\n")
    )
