"""Tests for keyboard builders — callbacks are now HMAC-signed."""

from alfred.bot.signing import verify_callback


def test_import_preview_keyboard_has_three_buttons() -> None:
    from alfred.bot.keyboards import import_preview_keyboard

    kb = import_preview_keyboard("user-123")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 3
    datas = [verify_callback(btn.callback_data) for btn in buttons]
    assert "import:clean_and_skip" in datas
    assert "import:import_all" in datas
    assert "import:review" in datas


def test_import_preview_keyboard_no_duplicates() -> None:
    from alfred.bot.keyboards import import_preview_keyboard

    kb = import_preview_keyboard("user-123", has_duplicates=False)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 2
    datas = [verify_callback(btn.callback_data) for btn in buttons]
    assert "import:confirm_all" in datas
    assert "import:cancel" in datas


def test_duplicate_review_keyboard_has_four_buttons() -> None:
    from alfred.bot.keyboards import duplicate_review_keyboard

    kb = duplicate_review_keyboard("user-123", 0)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 4
    datas = [verify_callback(btn.callback_data) for btn in buttons]
    assert any("dup_skip" in d for d in datas if d)
    assert any("dup_new" in d for d in datas if d)
    assert any("dup_merge" in d for d in datas if d)
    assert any("dup_replace" in d for d in datas if d)


def test_nudge_keyboard_is_signed() -> None:
    from alfred.bot.keyboards import nudge_keyboard

    kb = nudge_keyboard("test-nudge-id")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 4
    for btn in buttons:
        assert "|" in btn.callback_data
        data = verify_callback(btn.callback_data)
        assert data is not None
        assert data.startswith("nudge:")


def test_callback_data_within_64_byte_limit() -> None:
    from alfred.bot.keyboards import nudge_keyboard

    uuid = "12345678-1234-1234-1234-123456789abc"
    kb = nudge_keyboard(uuid)
    for row in kb.inline_keyboard:
        for btn in row:
            assert len(btn.callback_data.encode()) <= 64
