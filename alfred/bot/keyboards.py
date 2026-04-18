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


def date_confirm_keyboard(confirmation_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data=f"dateconfirm:yes:{confirmation_id}"),
        InlineKeyboardButton("✏️ Corrigir", callback_data=f"dateconfirm:edit:{confirmation_id}"),
    ]])


def import_confirm_keyboard(file_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar importação", callback_data=f"import:confirm:{file_id}"),
        InlineKeyboardButton("❌ Cancelar", callback_data="import:cancel"),
    ]])


def contact_action_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💾 Salvar", callback_data=f"contact:save:{contact_id}"),
            InlineKeyboardButton("✏️ Editar", callback_data=f"contact:edit:{contact_id}"),
            InlineKeyboardButton("🗑️ Descartar", callback_data=f"contact:discard:{contact_id}"),
        ]
    ])


def import_preview_keyboard(user_id: str, has_duplicates: bool = True) -> InlineKeyboardMarkup:
    """Grouped preview keyboard: 3 options when duplicates exist, 2 when clean."""
    if has_duplicates:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Importar novos + Pular duplicatas", callback_data=f"import:clean_and_skip:{user_id}")],
            [InlineKeyboardButton("📥 Importar todos como novos", callback_data=f"import:import_all:{user_id}")],
            [InlineKeyboardButton("🔍 Revisar duplicatas um a um", callback_data=f"import:review:{user_id}")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar importação", callback_data=f"import:confirm_all:{user_id}")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="import:cancel")],
    ])


def duplicate_review_keyboard(user_id: str, index: int) -> InlineKeyboardMarkup:
    """4 action buttons for reviewing a single duplicate."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏭ Pular", callback_data=f"import:dup_skip:{user_id}:{index}"),
            InlineKeyboardButton("➕ Importar novo", callback_data=f"import:dup_new:{user_id}:{index}"),
        ],
        [
            InlineKeyboardButton("🔀 Mesclar", callback_data=f"import:dup_merge:{user_id}:{index}"),
            InlineKeyboardButton("🔄 Substituir", callback_data=f"import:dup_replace:{user_id}:{index}"),
        ],
    ])
