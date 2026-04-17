"""Tests for contact service."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_list_contacts_searches_by_company() -> None:
    fake_result = MagicMock()
    fake_result.data = [
        {
            "display_name": "Ricardo Alves",
            "id": "c-1",
            "company": "BTG Pactual",
            "last_interaction_at": None,
        },
    ]

    fake_db = MagicMock()
    chain = fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value
    chain.or_.return_value.order.return_value.execute.return_value = fake_result

    with patch("alfred.services.contacts.get_db", return_value=fake_db):
        from alfred.services.contacts import list_contacts
        result = await list_contacts(user_id="u1", search="BTG Pactual")

    chain.or_.assert_called_once_with("display_name.ilike.%BTG Pactual%,company.ilike.%BTG Pactual%")
    assert "Ricardo Alves" in result
    assert "empresa: BTG Pactual" in result


@pytest.mark.asyncio
async def test_list_contacts_shows_company_in_output() -> None:
    fake_result = MagicMock()
    fake_result.data = [
        {
            "display_name": "Maria Silva",
            "id": "c-2",
            "company": "Google",
            "last_interaction_at": "2026-04-10T12:00:00",
        },
        {
            "display_name": "João Souza",
            "id": "c-3",
            "company": None,
            "last_interaction_at": None,
        },
    ]

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.order.return_value.execute.return_value = fake_result

    with patch("alfred.services.contacts.get_db", return_value=fake_db):
        from alfred.services.contacts import list_contacts
        result = await list_contacts(user_id="u1")

    assert "empresa: Google" in result
    assert "João Souza" in result
    assert "empresa:" not in result.split("João Souza")[1].split("\n")[0]
