def test_import_preview_keyboard_has_three_buttons() -> None:
    from alfred.bot.keyboards import import_preview_keyboard

    kb = import_preview_keyboard("user-123")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 3
    assert any("import:clean_and_skip:" in btn.callback_data for btn in buttons)
    assert any("import:import_all:" in btn.callback_data for btn in buttons)
    assert any("import:review:" in btn.callback_data for btn in buttons)


def test_import_preview_keyboard_no_duplicates() -> None:
    from alfred.bot.keyboards import import_preview_keyboard

    kb = import_preview_keyboard("user-123", has_duplicates=False)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 2
    assert any("import:confirm_all:" in btn.callback_data for btn in buttons)
    assert any("import:cancel" in btn.callback_data for btn in buttons)


def test_duplicate_review_keyboard_has_four_buttons() -> None:
    from alfred.bot.keyboards import duplicate_review_keyboard

    kb = duplicate_review_keyboard("user-123", 0)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 4
    assert any("dup_skip" in btn.callback_data for btn in buttons)
    assert any("dup_new" in btn.callback_data for btn in buttons)
    assert any("dup_merge" in btn.callback_data for btn in buttons)
    assert any("dup_replace" in btn.callback_data for btn in buttons)
