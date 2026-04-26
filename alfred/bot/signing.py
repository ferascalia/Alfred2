"""HMAC signing for Telegram callback data — prevents cross-user manipulation."""

import hashlib
import hmac

from alfred.config import settings


def _get_key() -> bytes:
    key = settings.webhook_secret or settings.jobs_secret or "alfred-fallback"
    return key.encode()


def sign_callback(data: str) -> str:
    sig = hmac.new(_get_key(), data.encode(), hashlib.sha256).hexdigest()[:8]
    return f"{data}|{sig}"


def verify_callback(signed: str) -> str | None:
    if "|" not in signed:
        return None
    data, sig = signed.rsplit("|", 1)
    expected = hmac.new(_get_key(), data.encode(), hashlib.sha256).hexdigest()[:8]
    if hmac.compare_digest(sig, expected):
        return data
    return None
