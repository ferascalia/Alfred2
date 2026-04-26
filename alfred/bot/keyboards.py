from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from alfred.bot.signing import sign_callback


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=sign_callback(data))


def nudge_keyboard(nudge_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _btn("📋 Copiar mensagem", f"nudge:copy:{nudge_id}"),
            _btn("✅ Já contatei", f"nudge:done:{nudge_id}"),
        ],
        [
            _btn("⏰ Adiar 7 dias", f"nudge:snooze:{nudge_id}"),
            _btn("🔇 Silenciar", f"nudge:mute:{nudge_id}"),
        ],
    ])


def confirm_keyboard(action: str, item_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _btn("✅ Confirmar", f"{action}:confirm:{item_id}"),
            _btn("❌ Cancelar", f"{action}:cancel:{item_id}"),
        ]
    ])


def date_confirm_keyboard(confirmation_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn("✅ Confirmar", f"dateconfirm:yes:{confirmation_id}"),
        _btn("✏️ Corrigir", f"dateconfirm:edit:{confirmation_id}"),
    ]])


def import_confirm_keyboard(file_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn("✅ Confirmar importação", f"import:confirm:{file_id}"),
        _btn("❌ Cancelar", "import:cancel"),
    ]])


def contact_action_keyboard(contact_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _btn("💾 Salvar", f"contact:save:{contact_id}"),
            _btn("✏️ Editar", f"contact:edit:{contact_id}"),
            _btn("🗑️ Descartar", f"contact:discard:{contact_id}"),
        ]
    ])


def import_preview_keyboard(user_id: str, has_duplicates: bool = True) -> InlineKeyboardMarkup:
    if has_duplicates:
        return InlineKeyboardMarkup([
            [_btn("✅ Importar novos + Pular duplicatas", "import:clean_and_skip")],
            [_btn("📥 Importar todos como novos", "import:import_all")],
            [_btn("🔍 Revisar duplicatas um a um", "import:review")],
        ])
    return InlineKeyboardMarkup([
        [_btn("✅ Confirmar importação", "import:confirm_all")],
        [_btn("❌ Cancelar", "import:cancel")],
    ])


def duplicate_review_keyboard(user_id: str, index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _btn("⏭ Pular", f"import:dup_skip:{index}"),
            _btn("➕ Importar novo", f"import:dup_new:{index}"),
        ],
        [
            _btn("🔀 Mesclar", f"import:dup_merge:{index}"),
            _btn("🔄 Substituir", f"import:dup_replace:{index}"),
        ],
    ])
