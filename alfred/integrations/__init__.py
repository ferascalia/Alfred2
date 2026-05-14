# alfred/integrations/__init__.py
"""Alfred integrations — plugin/adapter architecture."""

from alfred.integrations.registry import get_provider, list_providers, list_providers_by_category, register

__all__ = ["get_provider", "list_providers", "list_providers_by_category", "register"]
