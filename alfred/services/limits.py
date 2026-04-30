"""Per-user tier limits and enforcement."""

import structlog

from alfred.db.client import get_db
from alfred.services.usage import get_user_daily_messages, get_user_monthly_spend

log = structlog.get_logger()

TIER_LABELS: dict[str, str] = {
    "free": "Grátis",
    "personal": "Pessoal",
    "professional": "Profissional",
    "business": "Empresarial",
}

TIER_LIMITS: dict[str, dict] = {
    "free": {
        "max_contacts": 25,
        "max_messages_day": 15,
        "max_memories": 100,
        "voice": False,
        "budget_usd": 0.50,
    },
    "personal": {
        "max_contacts": 100,
        "max_messages_day": 50,
        "max_memories": 500,
        "voice": True,
        "budget_usd": 2.00,
    },
    "professional": {
        "max_contacts": 300,
        "max_messages_day": 100,
        "max_memories": 2000,
        "voice": True,
        "budget_usd": 5.00,
    },
    "business": {
        "max_contacts": 1000,
        "max_messages_day": 250,
        "max_memories": 10000,
        "voice": True,
        "budget_usd": 15.00,
    },
}


def get_limits(tier: str) -> dict:
    return TIER_LIMITS.get(tier, TIER_LIMITS["free"])


async def get_user_tier(user_id: str) -> str:
    try:
        db = get_db()
        result = db.table("users").select("tier").eq("id", user_id).single().execute()
        return result.data["tier"] if result.data else "free"
    except Exception:
        return "free"


async def build_status_text(user_id: str) -> str:
    db = get_db()
    tier = await get_user_tier(user_id)
    limits = get_limits(tier)

    daily_msgs = await get_user_daily_messages(user_id)
    monthly_spend = await get_user_monthly_spend(user_id)

    contact_count = (
        db.table("contacts")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("status", "active")
        .execute()
    )
    contacts = contact_count.count or 0

    memory_count = (
        db.table("memories")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    memories = memory_count.count or 0

    return (
        f"*Seu Alfred*\n\n"
        f"Plano: *{TIER_LABELS.get(tier, tier)}*\n\n"
        f"Contatos: {contacts}/{limits['max_contacts']}\n"
        f"Mensagens hoje: {daily_msgs}/{limits['max_messages_day']}\n"
        f"Memórias: {memories}/{limits['max_memories']}\n"
        f"Gasto mensal: ${monthly_spend:.2f} / ${limits['budget_usd']:.2f}\n"
        f"Voz: {'Sim' if limits['voice'] else 'Não'}"
    )


async def check_message_limit(user_id: str) -> tuple[bool, str]:
    tier = await get_user_tier(user_id)
    limits = get_limits(tier)

    daily_count = await get_user_daily_messages(user_id)
    if daily_count >= limits["max_messages_day"]:
        return False, (
            f"Você atingiu o limite de {limits['max_messages_day']} mensagens por dia "
            f"no plano {tier}. Tente novamente amanhã."
        )

    monthly_spend = await get_user_monthly_spend(user_id)
    if monthly_spend >= limits["budget_usd"]:
        return False, (
            f"Seu orçamento mensal de ${limits['budget_usd']:.2f} foi atingido "
            f"no plano {tier}."
        )

    return True, ""


async def check_contact_limit(user_id: str) -> tuple[bool, str]:
    tier = await get_user_tier(user_id)
    limits = get_limits(tier)

    try:
        db = get_db()
        result = (
            db.table("contacts")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("status", "active")
            .execute()
        )
        count = result.count or 0
    except Exception:
        log.exception("limits.contact_count_failed", user_id=user_id)
        return True, ""

    if count >= limits["max_contacts"]:
        return False, (
            f"Limite de {limits['max_contacts']} contatos ativos atingido "
            f"no plano {tier}."
        )
    return True, ""


async def check_memory_limit(user_id: str) -> tuple[bool, str]:
    tier = await get_user_tier(user_id)
    limits = get_limits(tier)

    try:
        db = get_db()
        result = (
            db.table("memories")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .execute()
        )
        count = result.count or 0
    except Exception:
        log.exception("limits.memory_count_failed", user_id=user_id)
        return True, ""

    if count >= limits["max_memories"]:
        return False, (
            f"Limite de {limits['max_memories']} memórias atingido "
            f"no plano {tier}."
        )
    return True, ""


async def check_voice_allowed(user_id: str) -> tuple[bool, str]:
    tier = await get_user_tier(user_id)
    limits = get_limits(tier)
    if not limits["voice"]:
        return False, "Mensagens de voz não estão disponíveis no plano gratuito."
    return True, ""
