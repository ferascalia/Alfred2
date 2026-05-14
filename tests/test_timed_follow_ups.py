"""Tests for timed follow-ups — timezone conversion and time_specific flag."""
import pytest
from unittest.mock import MagicMock, patch


def _make_db_mock(contact_name: str = "João", user_tz: str = "America/Sao_Paulo") -> MagicMock:
    fake_db = MagicMock()

    # contacts.select("display_name").eq(...).eq(...).single().execute()
    contact_result = MagicMock()
    contact_result.data = {"display_name": contact_name}
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = contact_result

    # users.select("timezone").eq(...).single().execute()
    user_result = MagicMock()
    user_result.data = {"timezone": user_tz}

    def table_router(name: str) -> MagicMock:
        if name == "users":
            m = MagicMock()
            m.select.return_value.eq.return_value.single.return_value.execute.return_value = user_result
            return m
        if name == "contacts":
            return fake_db.table.return_value
        return MagicMock()

    fake_db.table.side_effect = table_router
    # Re-set the contacts chain after side_effect override
    contacts_mock = MagicMock()
    contacts_mock.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = contact_result
    contacts_mock.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()

    def table_router_v2(name: str) -> MagicMock:
        if name == "users":
            m = MagicMock()
            m.select.return_value.eq.return_value.single.return_value.execute.return_value = user_result
            return m
        if name == "contacts":
            return contacts_mock
        return MagicMock()

    fake_db.table.side_effect = table_router_v2
    return fake_db, contacts_mock


@pytest.mark.asyncio
async def test_set_follow_up_with_time_converts_brt_to_utc() -> None:
    """17:00 BRT (UTC-3) should become 20:00 UTC."""
    fake_db, contacts_mock = _make_db_mock(user_tz="America/Sao_Paulo")

    with patch("alfred.services.contacts.get_db", return_value=fake_db):
        from alfred.services.contacts import set_follow_up
        result = await set_follow_up(
            user_id="u1", contact_id="c1", date="2026-05-07", time="17:00",
        )

    update_call = contacts_mock.update.call_args[0][0]
    assert update_call["time_specific"] is True
    assert "20:00" in update_call["next_nudge_at"]
    assert "às 17:00" in result


@pytest.mark.asyncio
async def test_set_follow_up_with_time_lisbon_timezone() -> None:
    """14:00 Europe/Lisbon (UTC+1 in summer) should become 13:00 UTC."""
    fake_db, contacts_mock = _make_db_mock(user_tz="Europe/Lisbon")

    with patch("alfred.services.contacts.get_db", return_value=fake_db):
        from alfred.services.contacts import set_follow_up
        result = await set_follow_up(
            user_id="u1", contact_id="c1", date="2026-07-15", time="14:00",
        )

    update_call = contacts_mock.update.call_args[0][0]
    assert update_call["time_specific"] is True
    assert "13:00" in update_call["next_nudge_at"]


@pytest.mark.asyncio
async def test_set_follow_up_without_time_stays_midnight_utc() -> None:
    """No time param should keep existing behavior — midnight UTC, time_specific=False."""
    fake_db, contacts_mock = _make_db_mock()

    with patch("alfred.services.contacts.get_db", return_value=fake_db):
        from alfred.services.contacts import set_follow_up
        result = await set_follow_up(
            user_id="u1", contact_id="c1", date="2026-05-10",
        )

    update_call = contacts_mock.update.call_args[0][0]
    assert update_call["time_specific"] is False
    assert "T00:00:00+00:00" in update_call["next_nudge_at"]
    assert "às" not in result


@pytest.mark.asyncio
async def test_set_follow_up_with_time_includes_note() -> None:
    fake_db, contacts_mock = _make_db_mock(contact_name="Maria")

    with patch("alfred.services.contacts.get_db", return_value=fake_db):
        from alfred.services.contacts import set_follow_up
        result = await set_follow_up(
            user_id="u1", contact_id="c1", date="2026-05-07",
            note="ligar pro escritório", time="09:30",
        )

    update_call = contacts_mock.update.call_args[0][0]
    assert update_call["follow_up_note"] == "ligar pro escritório"
    assert update_call["time_specific"] is True
    assert "Maria" in result
    assert "às 09:30" in result
    assert "ligar pro escritório" in result


@pytest.mark.asyncio
async def test_set_follow_up_invalid_date_returns_error() -> None:
    fake_db, _ = _make_db_mock()

    with patch("alfred.services.contacts.get_db", return_value=fake_db):
        from alfred.services.contacts import set_follow_up
        result = await set_follow_up(
            user_id="u1", contact_id="c1", date="not-a-date", time="17:00",
        )

    assert "Data inválida" in result
