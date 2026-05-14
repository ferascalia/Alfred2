# alfred/integrations/registry.py
"""Provider registry — explicit registration, factory lookup."""

from __future__ import annotations

from alfred.integrations.base import IntegrationProvider, ProviderInfo

_REGISTRY: dict[str, IntegrationProvider] = {}


def register(provider: IntegrationProvider) -> None:
    _REGISTRY[provider.info().slug] = provider


def get_provider(slug: str) -> IntegrationProvider | None:
    return _REGISTRY.get(slug)


def list_providers() -> list[ProviderInfo]:
    return [p.info() for p in _REGISTRY.values()]


def list_providers_by_category(category: str) -> list[ProviderInfo]:
    return [p.info() for p in _REGISTRY.values() if p.info().category == category]
