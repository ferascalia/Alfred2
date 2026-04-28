from typing import Any, TypedDict


class UserRow(TypedDict):
    id: str
    telegram_id: int
    name: str
    timezone: str
    locale: str
    tier: str
    status: str
    monthly_token_budget_usd: float
    max_contacts: int
    max_messages_per_day: int
    invited_by: str | None
    created_at: str


class ContactRow(TypedDict):
    id: str
    user_id: str
    display_name: str
    aliases: list[str]
    tags: list[str]
    how_we_met: str | None
    relationship_type: str | None
    company: str | None
    role: str | None
    email: str | None
    cadence_days: int
    last_interaction_at: str | None
    next_nudge_at: str | None
    follow_up_note: str | None
    status: str
    created_at: str
    updated_at: str


class MemoryRow(TypedDict):
    id: str
    user_id: str
    contact_id: str | None
    content: str
    kind: str
    source: str
    captured_at: str
    # embedding is omitted — not returned in normal queries


class InteractionRow(TypedDict):
    id: str
    user_id: str
    contact_id: str
    channel: str
    direction: str
    summary: str
    sentiment: str | None
    happened_at: str
    created_at: str


class NudgeRow(TypedDict):
    id: str
    user_id: str
    contact_id: str
    reason: str
    suggested_action: str
    draft_message: str
    status: str
    created_at: str
    acted_at: str | None


class ConversationRow(TypedDict):
    id: str
    user_id: str
    telegram_chat_id: int
    last_message_at: str


class MessageRow(TypedDict):
    id: str
    conversation_id: str
    role: str
    content: Any
    created_at: str


class ContactRelationshipRow(TypedDict):
    id: str
    user_id: str
    from_contact_id: str
    to_contact_id: str
    label: str
    created_at: str
