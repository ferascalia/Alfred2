"""Admin alert service — sends Telegram messages to the project admin."""

import structlog
from telegram import Bot

from alfred.config import settings

log = structlog.get_logger()


async def alert_admin(message: str) -> None:
    if not settings.admin_telegram_id:
        log.warning("alert_admin.no_admin_id")
        return
    try:
        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(
            chat_id=settings.admin_telegram_id,
            text=message,
            parse_mode="Markdown",
        )
    except Exception:
        log.exception("alert_admin.failed")
