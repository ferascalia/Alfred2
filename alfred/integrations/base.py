# alfred/integrations/base.py
"""Integration provider base — ABC and metadata for all integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderInfo:
    slug: str
    display_name: str
    emoji: str
    description: str
    category: str
    scopes_summary: str


class IntegrationProvider(ABC):

    @abstractmethod
    def info(self) -> ProviderInfo: ...

    @abstractmethod
    def build_auth_url(self, state: str) -> str: ...

    @abstractmethod
    async def exchange_code(self, code: str, state: str) -> dict[str, Any]: ...

    @abstractmethod
    async def refresh_tokens(self, user_id: str, refresh_token: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def list_events(self, user_id: str, start_date: str, **kwargs: Any) -> str: ...

    @abstractmethod
    async def create_event(self, user_id: str, title: str, start_datetime: str, end_datetime: str, **kwargs: Any) -> str: ...

    @abstractmethod
    async def update_event(self, user_id: str, event_id: str, fields: dict[str, Any]) -> str: ...

    @abstractmethod
    async def delete_event(self, user_id: str, event_id: str) -> str: ...
