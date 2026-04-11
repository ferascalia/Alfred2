from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def nudge_keyboard(nudge_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Copiar mensagem", callback_data=f"nudge:copy:{nudge_id}"),
            InlineKeyboardButton("✅ Já contatei", callback_data=f"nudge:done:{nudge_id}"),
        ],
        [
            InlineKeyboardButton("⏰ Adiar 7 dias", callback_data=f"nudge:snooze:{nudge_id}"),
            InlineKeyboardButton("🔇 Silenciar", callback_data=f"nudge:mute:{nudge_id}"),
        ],
    ])


def confirm_keyboard(action: str, item_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar", callback_data=f"{action}:confirm:{item_id}"),
            InlineKeyboardButton("❌ Cancelar", callback_data=f"{action}:cancel:{item_id}"),
        ]
    ])


def contact_action_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💾 Salvar", callback_data=f"contact:save:{contact_id}"),
            InlineKeyboardButton("✏️ Editar", callback_data=f"contact:edit:{contact_id}"),
            InlineKeyboardButton("🗑️ Descartar", callback_data=f"contact:discard:{contact_id}"),
        ]
    ])
