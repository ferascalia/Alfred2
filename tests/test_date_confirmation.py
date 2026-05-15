"""Unit tests for the date confirmation prompt detector."""


def test_plain_affirmation_is_not_confirmation_prompt() -> None:
    from alfred.agent.guardrails.date_confirmation import is_date_confirmation_prompt as _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt("Follow-up marcado para Daniel em 15/04/2026 ✅")


def test_confirmando_prefix_with_date_is_detected() -> None:
    from alfred.agent.guardrails.date_confirmation import is_date_confirmation_prompt as _is_date_confirmation_prompt

    assert _is_date_confirmation_prompt(
        "Confirmando: marcar follow-up do Daniel para amanhã, 15/04/2026 (quarta)?"
    )


def test_confirmando_prefix_case_insensitive() -> None:
    from alfred.agent.guardrails.date_confirmation import is_date_confirmation_prompt as _is_date_confirmation_prompt

    assert _is_date_confirmation_prompt("CONFIRMANDO: Daniel → 16/04/2026, posso gravar?")
    assert _is_date_confirmation_prompt("confirmando: Sofia → 15/04/2026, ok?")


def test_confirmando_with_iso_date() -> None:
    from alfred.agent.guardrails.date_confirmation import is_date_confirmation_prompt as _is_date_confirmation_prompt

    assert _is_date_confirmation_prompt("Confirmando: Daniel → 2026-04-16. Confere?")


def test_confirmando_without_date_is_rejected() -> None:
    from alfred.agent.guardrails.date_confirmation import is_date_confirmation_prompt as _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt("Confirmando: você quer registrar isso mesmo?")


def test_confirmando_not_at_start_is_rejected() -> None:
    from alfred.agent.guardrails.date_confirmation import is_date_confirmation_prompt as _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt(
        "Feito! Estou confirmando: o follow-up foi marcado para 15/04/2026"
    )


def test_confirmando_with_emoji_prefix_is_rejected() -> None:
    """Claude é instruído a NÃO colocar emoji antes de 'Confirmando:'.
    Se aparecer, preferimos cair no guardrail normal do que dar falso-positivo."""
    from alfred.agent.guardrails.date_confirmation import is_date_confirmation_prompt as _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt("📅 Confirmando: Daniel → 15/04/2026?")


def test_multi_line_confirmando_with_bullets() -> None:
    from alfred.agent.guardrails.date_confirmation import is_date_confirmation_prompt as _is_date_confirmation_prompt

    text = (
        "Confirmando:\n"
        "• Daniel — conversa hoje (14/04/2026) e follow-up quinta (16/04/2026)\n"
        "• Lorena — follow-up amanhã (15/04/2026)\n"
        "Posso gravar?"
    )
    assert _is_date_confirmation_prompt(text)


def test_empty_string_is_rejected() -> None:
    from alfred.agent.guardrails.date_confirmation import is_date_confirmation_prompt as _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt("")


def test_hallucinated_past_tense_confirmation_is_not_bypassed() -> None:
    """Alucinação clássica: 'marquei' no passado sem ter chamado a tool.
    Não pode ser confundida com o prompt de confirmação legítimo."""
    from alfred.agent.guardrails.date_confirmation import is_date_confirmation_prompt as _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt("Marquei o follow-up do Daniel para 15/04/2026 ✅")
    assert not _is_date_confirmation_prompt("Já registrei a conversa de 14/04/2026.")


# ── Scheduling disambiguation tests ──


def test_scheduling_disambiguation_detected() -> None:
    from alfred.agent.guardrails.date_confirmation import is_scheduling_disambiguation

    text = (
        "Escolha como agendar:\n"
        "• Hugo Rosa — 15/05/2026 (quinta) às 09:00"
    )
    assert is_scheduling_disambiguation(text)


def test_scheduling_disambiguation_case_insensitive() -> None:
    from alfred.agent.guardrails.date_confirmation import is_scheduling_disambiguation

    assert is_scheduling_disambiguation("escolha como agendar: Hugo — 15/05")
    assert is_scheduling_disambiguation("ESCOLHA COMO AGENDAR: teste")


def test_scheduling_disambiguation_not_mid_sentence() -> None:
    from alfred.agent.guardrails.date_confirmation import is_scheduling_disambiguation

    assert not is_scheduling_disambiguation("Posso te ajudar! Escolha como agendar: ...")


def test_scheduling_disambiguation_empty() -> None:
    from alfred.agent.guardrails.date_confirmation import is_scheduling_disambiguation

    assert not is_scheduling_disambiguation("")


def test_reminder_followup_detected() -> None:
    from alfred.agent.guardrails.date_confirmation import is_reminder_followup_prompt

    assert is_reminder_followup_prompt("Lembrete no Telegram?")
    assert is_reminder_followup_prompt("Lembrete no Telegram?\nQuer que eu crie um lembrete também?")


def test_reminder_followup_empty() -> None:
    from alfred.agent.guardrails.date_confirmation import is_reminder_followup_prompt

    assert not is_reminder_followup_prompt("")


def test_reminder_followup_not_mid_sentence() -> None:
    from alfred.agent.guardrails.date_confirmation import is_reminder_followup_prompt

    assert not is_reminder_followup_prompt("Evento criado! Lembrete no Telegram?")
