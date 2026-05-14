# tests/test_integrations.py
"""Tests for the integrations registry and provider base."""

import pytest


def test_provider_info_fields():
    from alfred.integrations.base import ProviderInfo

    info = ProviderInfo(
        slug="test_provider",
        display_name="Test Provider",
        emoji="🧪",
        description="A test provider",
        category="calendar",
        scopes_summary="Full access",
    )
    assert info.slug == "test_provider"
    assert info.category == "calendar"


def test_register_and_get_provider():
    from alfred.integrations.registry import get_provider, register, _REGISTRY
    from alfred.integrations.base import IntegrationProvider, ProviderInfo

    _REGISTRY.clear()

    class FakeProvider(IntegrationProvider):
        def info(self) -> ProviderInfo:
            return ProviderInfo(
                slug="fake",
                display_name="Fake",
                emoji="🧪",
                description="Fake",
                category="calendar",
                scopes_summary="None",
            )
        def build_auth_url(self, state): return ""
        async def exchange_code(self, code, state): return {}
        async def refresh_tokens(self, user_id, refresh_token): return None
        async def list_events(self, user_id, start_date, **kw): return ""
        async def create_event(self, user_id, title, start_datetime, end_datetime, **kw): return ""
        async def update_event(self, user_id, event_id, fields): return ""
        async def delete_event(self, user_id, event_id): return ""

    register(FakeProvider())
    assert get_provider("fake") is not None
    assert get_provider("fake").info().display_name == "Fake"


def test_get_provider_not_found():
    from alfred.integrations.registry import get_provider, _REGISTRY

    _REGISTRY.clear()
    assert get_provider("nonexistent") is None


def test_list_providers():
    from alfred.integrations.registry import list_providers, register, _REGISTRY
    from alfred.integrations.base import IntegrationProvider, ProviderInfo

    _REGISTRY.clear()

    class FakeProvider(IntegrationProvider):
        def info(self) -> ProviderInfo:
            return ProviderInfo(
                slug="fake", display_name="Fake", emoji="🧪",
                description="Fake", category="calendar", scopes_summary="None",
            )
        def build_auth_url(self, state): return ""
        async def exchange_code(self, code, state): return {}
        async def refresh_tokens(self, user_id, refresh_token): return None
        async def list_events(self, user_id, start_date, **kw): return ""
        async def create_event(self, user_id, title, start_datetime, end_datetime, **kw): return ""
        async def update_event(self, user_id, event_id, fields): return ""
        async def delete_event(self, user_id, event_id): return ""

    register(FakeProvider())
    providers = list_providers()
    assert len(providers) == 1
    assert providers[0].slug == "fake"


def test_list_providers_by_category():
    from alfred.integrations.registry import list_providers_by_category, register, _REGISTRY
    from alfred.integrations.base import IntegrationProvider, ProviderInfo

    _REGISTRY.clear()

    class CalendarProvider(IntegrationProvider):
        def info(self) -> ProviderInfo:
            return ProviderInfo(
                slug="cal", display_name="Cal", emoji="📅",
                description="Cal", category="calendar", scopes_summary="None",
            )
        def build_auth_url(self, state): return ""
        async def exchange_code(self, code, state): return {}
        async def refresh_tokens(self, user_id, refresh_token): return None
        async def list_events(self, user_id, start_date, **kw): return ""
        async def create_event(self, user_id, title, start_datetime, end_datetime, **kw): return ""
        async def update_event(self, user_id, event_id, fields): return ""
        async def delete_event(self, user_id, event_id): return ""

    register(CalendarProvider())
    assert len(list_providers_by_category("calendar")) == 1
    assert len(list_providers_by_category("crm")) == 0


# ---------------------------------------------------------------------------
# Generic OAuth service tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_tokens():
    from unittest.mock import MagicMock, patch
    from alfred.services.oauth import store_tokens

    fake_db = MagicMock()
    fake_db.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{}])

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        await store_tokens("user-1", "google_calendar", {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_at": "2026-06-01T00:00:00+00:00",
            "scopes": ["calendar"],
        })

    upsert_call = fake_db.table.return_value.upsert.call_args[0][0]
    assert upsert_call["user_id"] == "user-1"
    assert upsert_call["provider"] == "google_calendar"
    assert upsert_call["access_token"] == "tok"
    assert upsert_call["status"] == "active"


@pytest.mark.asyncio
async def test_get_tokens_found():
    from unittest.mock import MagicMock, patch
    from alfred.services.oauth import get_tokens

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"access_token": "tok", "refresh_token": "ref", "token_expires_at": None, "scopes": [], "status": "active"}
    )

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        result = await get_tokens("user-1", "google_calendar")

    assert result is not None
    assert result["access_token"] == "tok"


@pytest.mark.asyncio
async def test_get_tokens_not_found():
    from unittest.mock import MagicMock, patch
    from alfred.services.oauth import get_tokens

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        result = await get_tokens("user-1", "google_calendar")

    assert result is None


@pytest.mark.asyncio
async def test_has_integration_true():
    from unittest.mock import MagicMock, patch
    from alfred.services.oauth import has_integration

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"status": "active"}]
    )

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        assert await has_integration("user-1", "google_calendar") is True


@pytest.mark.asyncio
async def test_has_integration_false():
    from unittest.mock import MagicMock, patch
    from alfred.services.oauth import has_integration

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        assert await has_integration("user-1", "google_calendar") is False


@pytest.mark.asyncio
async def test_revoke_integration():
    from unittest.mock import MagicMock, patch
    from alfred.services.oauth import revoke_integration

    fake_db = MagicMock()
    fake_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        assert await revoke_integration("user-1", "google_calendar") is True


@pytest.mark.asyncio
async def test_get_active_calendar_provider_found():
    from unittest.mock import MagicMock, patch
    from alfred.services.oauth import get_active_calendar_provider
    from alfred.integrations.registry import register, _REGISTRY
    from alfred.integrations.base import IntegrationProvider, ProviderInfo

    _REGISTRY.clear()

    class FakeCal(IntegrationProvider):
        def info(self): return ProviderInfo(
            slug="google_calendar", display_name="GCal", emoji="📅",
            description="", category="calendar", scopes_summary="",
        )
        def build_auth_url(self, state): return ""
        async def exchange_code(self, code, state): return {}
        async def refresh_tokens(self, user_id, refresh_token): return None
        async def list_events(self, user_id, start_date, **kw): return ""
        async def create_event(self, user_id, title, start_datetime, end_datetime, **kw): return ""
        async def update_event(self, user_id, event_id, fields): return ""
        async def delete_event(self, user_id, event_id): return ""

    register(FakeCal())

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"provider": "google_calendar"}]
    )

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        result = await get_active_calendar_provider("user-1")

    assert result == "google_calendar"


@pytest.mark.asyncio
async def test_get_active_calendar_provider_none():
    from unittest.mock import MagicMock, patch
    from alfred.services.oauth import get_active_calendar_provider

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    with patch("alfred.services.oauth.get_db", return_value=fake_db):
        result = await get_active_calendar_provider("user-1")

    assert result is None
