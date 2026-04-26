"""API usage tracking and budget alert system."""

from datetime import datetime, timezone

import structlog

from alfred.config import settings
from alfred.db.client import get_db
from alfred.services.alerts import alert_admin

log = structlog.get_logger()

# Pricing per 1M tokens (USD) — Sonnet 4.6
_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
        "cache_read": 0.08,
        "cache_write": 1.00,
    },
}

_THRESHOLDS = [0.70, 0.85, 0.95]


def _compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> float:
    prices = _PRICING.get(model, _PRICING["claude-sonnet-4-6"])
    billable_input = input_tokens - cache_read_tokens - cache_write_tokens
    cost = (
        max(billable_input, 0) * prices["input"]
        + output_tokens * prices["output"]
        + cache_read_tokens * prices["cache_read"]
        + cache_write_tokens * prices["cache_write"]
    ) / 1_000_000
    return cost


async def record_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    user_id: str | None = None,
) -> None:
    cost = _compute_cost(
        model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
    )

    try:
        db = get_db()
        db.table("api_usage").insert(
            {
                "user_id": user_id,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_write_tokens": cache_write_tokens,
                "cost_usd": float(cost),
            }
        ).execute()
    except Exception:
        log.exception("usage.record_failed")
        return

    log.info(
        "usage.recorded",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
    )

    await _check_budget_alerts()


async def get_monthly_spend() -> float:
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        db = get_db()
        result = (
            db.table("api_usage")
            .select("cost_usd")
            .gte("created_at", month_start.isoformat())
            .execute()
        )
        return sum(row["cost_usd"] for row in result.data)
    except Exception:
        log.exception("usage.get_spend_failed")
        return 0.0


async def get_user_monthly_spend(user_id: str) -> float:
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        db = get_db()
        result = (
            db.table("api_usage")
            .select("cost_usd")
            .eq("user_id", user_id)
            .gte("created_at", month_start.isoformat())
            .execute()
        )
        return sum(row["cost_usd"] for row in result.data)
    except Exception:
        log.exception("usage.get_user_spend_failed", user_id=user_id)
        return 0.0


async def get_user_daily_messages(user_id: str) -> int:
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        db = get_db()
        result = (
            db.table("api_usage")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("created_at", day_start.isoformat())
            .neq("model", "__alert__")
            .execute()
        )
        return result.count or 0
    except Exception:
        log.exception("usage.get_user_daily_failed", user_id=user_id)
        return 0


async def _check_budget_alerts() -> None:
    budget = settings.anthropic_monthly_budget_usd
    if budget <= 0:
        return

    spent = await get_monthly_spend()
    ratio = spent / budget

    for threshold in _THRESHOLDS:
        if ratio >= threshold:
            alert_key = f"budget_alert_{threshold}"
            if await _already_alerted(alert_key):
                continue

            now = datetime.now(timezone.utc)
            days_elapsed = max(now.day, 1)
            daily_avg = spent / days_elapsed
            days_remaining = (budget - spent) / daily_avg if daily_avg > 0 else 999

            if threshold == 0.70:
                msg = (
                    f"⚠️ *Alerta de Budget Alfred*\n\n"
                    f"Consumo atingiu *{threshold:.0%}* do budget mensal.\n"
                    f"Gasto: ${spent:.2f} / ${budget:.2f}\n"
                    f"Ritmo: ~${daily_avg:.2f}/dia"
                )
            elif threshold == 0.85:
                msg = (
                    f"🔶 *Budget em {threshold:.0%}!*\n\n"
                    f"Gasto: ${spent:.2f} / ${budget:.2f}\n"
                    f"Estimativa: acaba em ~{days_remaining:.0f} dias"
                )
            else:
                msg = (
                    f"🚨 *URGENTE: {threshold:.0%} do budget!*\n\n"
                    f"Restam ~${budget - spent:.2f}\n"
                    f"Recarregue agora: console.anthropic.com"
                )

            await alert_admin(msg)
            await _mark_alerted(alert_key)
            break


async def _already_alerted(key: str) -> bool:
    now = datetime.now(timezone.utc)
    month_tag = now.strftime("%Y-%m")
    full_key = f"{key}_{month_tag}"
    try:
        db = get_db()
        result = (
            db.table("api_usage")
            .select("id")
            .eq("model", f"__alert__{full_key}")
            .limit(1)
            .execute()
        )
        return len(result.data) > 0
    except Exception:
        return False


async def _mark_alerted(key: str) -> None:
    now = datetime.now(timezone.utc)
    month_tag = now.strftime("%Y-%m")
    full_key = f"{key}_{month_tag}"
    try:
        db = get_db()
        db.table("api_usage").insert(
            {
                "model": f"__alert__{full_key}",
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cost_usd": 0,
            }
        ).execute()
    except Exception:
        log.exception("usage.mark_alert_failed")
