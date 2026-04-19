"""Eval dataset: consultas não devem triggar pending actions; ações devem."""

import pytest

from alfred.agent.loop import _detect_pending_actions


class TestGuardrailDoesNotBlockQueries:
    """Consultas de leitura não devem triggar pending actions."""

    @pytest.mark.parametrize(
        "msg,tools",
        [
            ("me mostra os follow-ups da próxima semana", {"list_follow_ups"}),
            ("quais meus follow-ups de amanhã?", {"list_follow_ups"}),
            ("o que eu tenho marcado pro dia 20?", {"list_follow_ups"}),
            ("lista meus lembretes dessa semana", {"list_follow_ups"}),
            ("quem eu tenho pra falar essa semana?", {"list_follow_ups"}),
            ("mostra os follow-ups do mês que vem", {"list_follow_ups"}),
            ("quem eu conheço no Agibank?", {"list_contacts", "search_memories"}),
            ("me mostra todos os meus contatos", {"list_contacts"}),
            ("quantos contatos eu tenho?", {"list_contacts"}),
            ("o que eu sei sobre o João?", {"list_contacts", "search_memories"}),
            ("me lembra o que a Maria faz", {"list_contacts", "get_contact_digest"}),
        ],
        ids=[
            "followups-proxima-semana",
            "followups-amanha",
            "followups-dia-20",
            "followups-lembretes-semana",
            "followups-falar-semana",
            "followups-mes-que-vem",
            "contacts-empresa",
            "contacts-todos",
            "contacts-quantos",
            "memories-sobre",
            "memories-lembra-que-faz",
        ],
    )
    def test_query_not_blocked(self, msg, tools):
        missing = _detect_pending_actions(msg, tools)
        assert missing == [], f"Query '{msg}' was incorrectly blocked: {missing}"


class TestGuardrailStillCatchesActions:
    """Ações reais continuam sendo detectadas."""

    @pytest.mark.parametrize(
        "msg,tools,expected_tool",
        [
            ("falei com o João hoje", set(), "log_interaction"),
            ("conversei com a Maria ontem", set(), "log_interaction"),
            ("encontrei o Pedro no almoço", set(), "log_interaction"),
            ("marca follow-up do Daniel pra quinta", set(), "set_follow_up"),
            ("agenda pro dia 20 com a Maria", set(), "set_follow_up"),
            ("me lembra de falar com ele semana que vem", set(), "set_follow_up"),
            ("reagenda o João pra próxima semana", set(), "set_follow_up"),
            ("muda a cadência do João pra toda terça", set(), "set_cadence"),
            ("quero falar com ele a cada 15 dias", set(), "set_cadence"),
        ],
        ids=[
            "interaction-falei",
            "interaction-conversei",
            "interaction-encontrei",
            "followup-marca",
            "followup-agenda-dia",
            "followup-me-lembra",
            "followup-reagenda",
            "cadence-toda-terca",
            "cadence-cada-15-dias",
        ],
    )
    def test_action_still_detected(self, msg, tools, expected_tool):
        missing = _detect_pending_actions(msg, tools)
        assert any(
            expected_tool in m for m in missing
        ), f"Action '{msg}' should require {expected_tool} but got: {missing}"


class TestGuardrailActionSatisfied:
    """Quando a tool correta foi chamada, guardrail não reclama."""

    @pytest.mark.parametrize(
        "msg,tools",
        [
            ("falei com o João hoje", {"log_interaction"}),
            ("marca follow-up pra quinta", {"set_follow_up"}),
            ("me lembra de ligar semana que vem", {"set_follow_up"}),
            ("muda pra toda terça", {"set_cadence"}),
        ],
    )
    def test_action_satisfied(self, msg, tools):
        missing = _detect_pending_actions(msg, tools)
        assert missing == [], f"Action '{msg}' with tools {tools} should be satisfied"
