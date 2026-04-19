"""Tests for composable system prompt sections."""

from alfred.agent.prompt_sections import build_system_prompt


class TestBuildSystemPrompt:
    def test_query_excludes_action_rules(self):
        prompt = build_system_prompt("QUERY", "2026-04-19")
        assert "list_follow_ups" in prompt
        assert "Confirmando:" not in prompt
        assert "log_interaction" not in prompt

    def test_query_includes_empty_data_guidance(self):
        prompt = build_system_prompt("QUERY", "2026-04-19")
        assert "Nunca invente dados" in prompt

    def test_action_includes_date_confirm(self):
        prompt = build_system_prompt("ACTION", "2026-04-19")
        assert "Confirmando:" in prompt
        assert "create_contact" in prompt

    def test_action_excludes_multi_action(self):
        prompt = build_system_prompt("ACTION", "2026-04-19")
        assert "Multi-ação e multi-contato" not in prompt

    def test_multi_action_includes_all(self):
        prompt = build_system_prompt("MULTI_ACTION", "2026-04-19")
        assert "Confirmando:" in prompt
        assert "Multi-ação e multi-contato" in prompt
        assert "create_contact" in prompt

    def test_conversation_minimal(self):
        prompt = build_system_prompt("CONVERSATION", "2026-04-19")
        action_prompt = build_system_prompt("ACTION", "2026-04-19")
        assert len(prompt) < len(action_prompt)
        assert "Confirmando:" not in prompt
        assert "Alfred" in prompt  # persona still present

    def test_datetime_appended(self):
        prompt = build_system_prompt("QUERY", "2026-04-19 (Saturday, 14:30 BRT)")
        assert "2026-04-19" in prompt
        assert "Saturday" in prompt

    def test_unknown_intent_defaults_to_action(self):
        prompt = build_system_prompt("UNKNOWN", "2026-04-19")
        action_prompt = build_system_prompt("ACTION", "2026-04-19")
        assert prompt == action_prompt


class TestToolFiltering:
    def test_query_tools_read_only(self):
        from alfred.agent.tools import get_tools_for_intent
        tools = get_tools_for_intent("QUERY")
        names = {t["name"] for t in tools}
        assert "list_contacts" in names
        assert "list_follow_ups" in names
        assert "search_memories" in names
        assert "create_contact" not in names
        assert "set_follow_up" not in names

    def test_action_tools_all(self):
        from alfred.agent.tools import get_tools_for_intent
        tools = get_tools_for_intent("ACTION")
        names = {t["name"] for t in tools}
        assert "list_contacts" in names
        assert "create_contact" in names
        assert "set_follow_up" in names

    def test_conversation_no_tools(self):
        from alfred.agent.tools import get_tools_for_intent
        tools = get_tools_for_intent("CONVERSATION")
        assert tools == []

    def test_unknown_defaults_to_all(self):
        from alfred.agent.tools import get_tools_for_intent
        tools = get_tools_for_intent("UNKNOWN")
        names = {t["name"] for t in tools}
        assert "create_contact" in names
        assert "list_contacts" in names
