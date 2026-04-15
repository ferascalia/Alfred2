"""Unit tests for the date confirmation prompt detector."""


def test_plain_affirmation_is_not_confirmation_prompt() -> None:
    from alfred.agent.loop import _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt("Follow-up marcado para Daniel em 15/04/2026 ✅")


def test_confirmando_prefix_with_date_is_detected() -> None:
    from alfred.agent.loop import _is_date_confirmation_prompt

    assert _is_date_confirmation_prompt(
        "Confirmando: marcar follow-up do Daniel para amanhã, 15/04/2026 (quarta)?"
    )


def test_confirmando_prefix_case_insensitive() -> None:
    from alfred.agent.loop import _is_date_confirmation_prompt

    assert _is_date_confirmation_prompt("CONFIRMANDO: Daniel → 16/04/2026, posso gravar?")
    assert _is_date_confirmation_prompt("confirmando: Sofia → 15/04/2026, ok?")


def test_confirmando_with_iso_date() -> None:
    from alfred.agent.loop import _is_date_confirmation_prompt

    assert _is_date_confirmation_prompt("Confirmando: Daniel → 2026-04-16. Confere?")


def test_confirmando_without_date_is_rejected() -> None:
    from alfred.agent.loop import _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt("Confirmando: você quer registrar isso mesmo?")


def test_confirmando_not_at_start_is_rejected() -> None:
    from alfred.agent.loop import _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt(
        "Feito! Estou confirmando: o follow-up foi marcado para 15/04/2026"
    )


def test_confirmando_with_emoji_prefix_is_rejected() -> None:
    """Claude é instruído a NÃO colocar emoji antes de 'Confirmando:'.
    Se aparecer, preferimos cair no guardrail normal do que dar falso-positivo."""
    from alfred.agent.loop import _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt("📅 Confirmando: Daniel → 15/04/2026?")


def test_multi_line_confirmando_with_bullets() -> None:
    from alfred.agent.loop import _is_date_confirmation_prompt

    text = (
        "Confirmando:\n"
        "• Daniel — conversa hoje (14/04/2026) e follow-up quinta (16/04/2026)\n"
        "• Lorena — follow-up amanhã (15/04/2026)\n"
        "Posso gravar?"
    )
    assert _is_date_confirmation_prompt(text)


def test_empty_string_is_rejected() -> None:
    from alfred.agent.loop import _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt("")


def test_hallucinated_past_tense_confirmation_is_not_bypassed() -> None:
    """Alucinação clássica: 'marquei' no passado sem ter chamado a tool.
    Não pode ser confundida com o prompt de confirmação legítimo."""
    from alfred.agent.loop import _is_date_confirmation_prompt

    assert not _is_date_confirmation_prompt("Marquei o follow-up do Daniel para 15/04/2026 ✅")
    assert not _is_date_confirmation_prompt("Já registrei a conversa de 14/04/2026.")
