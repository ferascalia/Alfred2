"""Tests for HMAC callback signing."""

from alfred.bot.signing import sign_callback, verify_callback


def test_sign_and_verify_roundtrip() -> None:
    data = "nudge:copy:abc-123"
    signed = sign_callback(data)
    assert signed != data
    assert "|" in signed
    assert verify_callback(signed) == data


def test_verify_rejects_tampered_data() -> None:
    signed = sign_callback("nudge:copy:abc-123")
    tampered = signed.replace("abc-123", "xyz-999")
    assert verify_callback(tampered) is None


def test_verify_rejects_no_separator() -> None:
    assert verify_callback("nudge:copy:abc-123") is None


def test_verify_rejects_wrong_signature() -> None:
    data = "nudge:copy:abc-123"
    assert verify_callback(f"{data}|deadbeef") is None


def test_signed_data_within_64_bytes() -> None:
    uuid = "12345678-1234-1234-1234-123456789abc"
    long_data = f"nudge:snooze:{uuid}"
    signed = sign_callback(long_data)
    assert len(signed.encode()) <= 64


def test_import_callback_within_64_bytes() -> None:
    signed = sign_callback("import:clean_and_skip")
    assert len(signed.encode()) <= 64


def test_dup_review_callback_within_64_bytes() -> None:
    signed = sign_callback("import:dup_replace:99")
    assert len(signed.encode()) <= 64
