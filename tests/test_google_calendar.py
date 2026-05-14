"""Backward-compat test — ensures integration registry replaces old Google Calendar service."""

import pytest


def test_old_google_calendar_service_deleted():
    """Verify the old hardcoded service no longer exists."""
    with pytest.raises(ModuleNotFoundError):
        import alfred.services.google_calendar  # noqa: F401


def test_integration_registry_has_google_calendar():
    from alfred.integrations import get_provider

    provider = get_provider("google_calendar")
    assert provider is not None
    assert provider.info().slug == "google_calendar"


def test_schemas_calendar_integration_tools():
    from alfred.agent.tools.schemas import CALENDAR_INTEGRATION_TOOLS

    names = [t["name"] for t in CALENDAR_INTEGRATION_TOOLS]
    assert "list_calendar_events" in names
    assert "create_calendar_event" in names
    assert "update_calendar_event" in names


def test_schemas_no_google_in_descriptions():
    from alfred.agent.tools.schemas import CALENDAR_INTEGRATION_TOOLS

    for tool in CALENDAR_INTEGRATION_TOOLS:
        assert "Google" not in tool["description"], f"Tool {tool['name']} still references Google"


def test_activity_agent_has_calendar_tools():
    from alfred.agent.agents.activity import ActivityAgent

    agent = ActivityAgent()
    tool_names = [t["name"] for t in agent.get_tools()]
    assert "list_calendar_events" in tool_names
    assert "create_calendar_event" in tool_names
    assert "update_calendar_event" in tool_names


def test_query_agent_has_list_calendar_events():
    from alfred.agent.agents.query import QueryAgent

    agent = QueryAgent()
    tool_names = [t["name"] for t in agent.get_tools()]
    assert "list_calendar_events" in tool_names


def test_prompt_no_google_calendar_hardcoded():
    from alfred.agent.agents.activity import ActivityAgent
    from alfred.agent.context import AgentContext

    agent = ActivityAgent()
    ctx = AgentContext(
        user_id="u1", telegram_id=123, user_name="Test",
        message="test", current_date="2026-05-14", is_confirmation=False,
    )
    prompt = agent.build_prompt(ctx)
    assert "Google Calendar" not in prompt
    assert "list_calendar_events" in prompt
    assert "Agendando:" in prompt


def test_has_calendar_confirmation():
    from alfred.bot.handlers import _has_calendar_confirmation

    assert _has_calendar_confirmation("Agendando:\n• Reunião com João")
    assert _has_calendar_confirmation("  agendando: algo")
    assert not _has_calendar_confirmation("Confirmando: algo")
    assert not _has_calendar_confirmation("Algum texto normal")


def test_calendar_confirm_keyboard():
    from alfred.bot.keyboards import calendar_confirm_keyboard

    kb = calendar_confirm_keyboard("abc123")
    buttons = kb.inline_keyboard[0]
    assert len(buttons) == 2
    assert "Agendar" in buttons[0].text
