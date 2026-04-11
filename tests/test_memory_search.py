"""Tests for memory service."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_search_memories_returns_formatted_results() -> None:
    fake_embedding = [0.1] * 1024

    fake_db_result = MagicMock()
    fake_db_result.data = [
        {"kind": "milestone", "content": "Vai ter um filho em agosto"},
        {"kind": "personal", "content": "Mora em Florianópolis"},
    ]

    fake_db = MagicMock()
    fake_db.rpc.return_value.execute.return_value = fake_db_result

    with (
        patch("alfred.services.memories._embed", AsyncMock(return_value=fake_embedding)),
        patch("alfred.services.memories.get_db", return_value=fake_db),
    ):
        from alfred.services.memories import search_memories
        result = await search_memories(
            user_id="test-user",
            query="filho agosto",
            contact_id="contact-123",
        )

    assert "milestone" in result
    assert "agosto" in result
    assert "Florianópolis" in result


@pytest.mark.asyncio
async def test_search_memories_empty_returns_message() -> None:
    fake_embedding = [0.0] * 1024

    fake_db_result = MagicMock()
    fake_db_result.data = []

    fake_db = MagicMock()
    fake_db.rpc.return_value.execute.return_value = fake_db_result

    with (
        patch("alfred.services.memories._embed", AsyncMock(return_value=fake_embedding)),
        patch("alfred.services.memories.get_db", return_value=fake_db),
    ):
        from alfred.services.memories import search_memories
        result = await search_memories(user_id="test-user", query="xyz irrelevante")

    assert "Nenhuma memória" in result


@pytest.mark.asyncio
async def test_add_memory_embeds_and_inserts() -> None:
    fake_embedding = [0.5] * 1024

    fake_db_result = MagicMock()
    fake_db_result.data = [{"id": "mem-1"}]

    fake_db = MagicMock()
    fake_db.table.return_value.insert.return_value.execute.return_value = fake_db_result

    with (
        patch("alfred.services.memories._embed", AsyncMock(return_value=fake_embedding)),
        patch("alfred.services.memories.get_db", return_value=fake_db),
    ):
        from alfred.services.memories import add_memory
        result = await add_memory(
            user_id="u1",
            contact_id="c1",
            content="Adora café especial",
            kind="preference",
        )

    assert "Memória registrada" in result
    fake_db.table.assert_called_with("memories")
