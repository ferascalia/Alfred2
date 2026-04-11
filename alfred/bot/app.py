from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from alfred.bot.handlers import callback_handler, message_handler, start_handler, voice_handler
from alfred.config import settings


def build_application() -> Application:  # type: ignore[type-arg]
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .updater(None)  # Webhook mode — no polling
        .build()
    )

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )
    app.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, voice_handler)
    )

    return app
