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


def test_tool_schemas_have_required_fields() -> None:
    from alfred.agent.tools import TOOL_SCHEMAS

    for tool in TOOL_SCHEMAS:
        assert "name" in tool, f"Tool missing 'name': {tool}"
        assert "description" in tool, f"Tool missing 'description': {tool}"
        assert "input_schema" in tool, f"Tool missing 'input_schema': {tool}"
