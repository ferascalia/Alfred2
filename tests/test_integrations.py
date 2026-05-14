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
