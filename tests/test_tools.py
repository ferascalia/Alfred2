"""Unit tests for agent tool dispatch."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_dispatch_unknown_tool() -> None:
    from alfred.agent.tools import dispatch_tool

    result = await dispatch_tool("nonexistent_tool", {}, user_id="test-user")
    assert "não reconhecida" in result


@pytest.mark.asyncio
async def test_dispatch_list_contacts_calls_service() -> None:
    from alfred.agent.tools import dispatch_tool

    mock_result = "- **João Silva** (id: abc-123)"
    with patch("alfred.services.contacts.list_contacts", AsyncMock(return_value=mock_result)):
        result = await dispatch_tool(
            "list_contacts",
            {"limit": 10},
            user_id="test-user-id",
        )
    assert "João Silva" in result


@pytest.mark.asyncio
async def test_dispatch_create_contact() -> None:
    from alfred.agent.tools import dispatch_tool

    expected = "Contato **Maria Oliveira** criado com sucesso (id: xyz-456)."
    with patch("alfred.services.contacts.create_contact", AsyncMock(return_value=expected)):
        result = await dispatch_tool(
            "create_contact",
            {"display_name": "Maria Oliveira"},
            user_id="test-user-id",
        )
    assert "Maria Oliveira" in result


@pytest.mark.asyncio
async def test_dispatch_add_memory() -> None:
    from alfred.agent.tools import dispatch_tool

    expected = "Memória registrada: Vai ter um filho em agosto."
    with patch("alfred.services.memories.add_memory", AsyncMock(return_value=expected)):
        result = await dispatch_tool(
            "add_memory",
            {"contact_id": "abc", "content": "Vai ter um filho em agosto.", "kind": "milestone"},
            user_id="test-user-id",
        )
    assert "Memória registrada" in result


@pytest.mark.asyncio
async def test_dispatch_list_follow_ups_calls_service() -> None:
    from alfred.agent.tools import dispatch_tool

    expected = "**Follow-ups agendados até 20/04/2026:**\n- **Daniel** (id: abc) → 2026-04-15"
    with patch(
        "alfred.services.contacts.list_upcoming_follow_ups",
        AsyncMock(return_value=expected),
    ):
        result = await dispatch_tool(
            "list_follow_ups",
            {"until_date": "2026-04-20"},
            user_id="test-user-id",
        )
    assert "Daniel" in result
    assert "Follow-ups agendados" in result


@pytest.mark.asyncio
async def test_list_upcoming_follow_ups_empty_does_not_invent() -> None:
    from alfred.services import contacts as contacts_service

    fake_db = MagicMock()
    query = MagicMock()
    fake_db.table.return_value = query
    query.select.return_value = query
    query.eq.return_value = query
    query.not_.is_.return_value = query
    query.lte.return_value = query
    query.order.return_value = query
    query.execute.return_value = MagicMock(data=[])

    with patch("alfred.services.contacts.get_db", return_value=fake_db):
        result = await contacts_service.list_upcoming_follow_ups(
            user_id="test-user",
            until_date="2026-04-20",
        )
    assert "Nenhum follow-up" in result
    assert "NÃO invente" in result


@pytest.mark.asyncio
async def test_list_upcoming_follow_ups_invalid_date() -> None:
    from alfred.services.contacts import list_upcoming_follow_ups

    result = await list_upcoming_follow_ups(user_id="test-user", until_date="amanhã")
    assert "Data inválida" in result


def test_tool_schemas_have_required_fields() -> None:
    from alfred.agent.tools import TOOL_SCHEMAS

    for tool in TOOL_SCHEMAS:
        assert "name" in tool, f"Tool missing 'name': {tool}"
        assert "description" in tool, f"Tool missing 'description': {tool}"
        assert "input_schema" in tool, f"Tool missing 'input_schema': {tool}"
