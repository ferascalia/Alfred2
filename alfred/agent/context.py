"""Shared context for multi-agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from anthropic.types import MessageParam

BRT = timezone(timedelta(hours=-3))


@dataclass
class AgentContext:
    user_id: str
    telegram_id: int
    user_name: str
    message: str
    intent: str = ""
    current_date: str = ""
    is_confirmation: bool = False

    tools_called: set[str] = field(default_factory=set)
    tool_calls_log: list[tuple[str, dict]] = field(default_factory=list)
    pending_retries: int = 0
    created_entities: dict[str, str] = field(default_factory=dict)

    history: list[MessageParam] = field(default_factory=list)

    @staticmethod
    def make_date_str() -> str:
        now = datetime.now(BRT)
        return now.strftime("%Y-%m-%d (%A, %H:%M BRT)")


@dataclass
class AgentResult:
    text: str
    tools_called: set[str] = field(default_factory=set)
    tool_calls_log: list[tuple[str, dict]] = field(default_factory=list)
    created_entities: dict[str, str] = field(default_factory=dict)
