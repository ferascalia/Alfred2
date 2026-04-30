"""HMAC signing for Telegram callback data — prevents cross-user manipulation."""

import hashlib
import hmac
import logging

from alfred.config import settings

_warned = False


def _get_key() -> bytes:
    global _warned
    key = settings.webhook_secret or settings.jobs_secret
    if not key:
        if not _warned:
            logging.getLogger(__name__).warning(
                "Neither webhook_secret nor jobs_secret is set — "
                "callback signing is insecure. Set at least one in production."
            )
            _warned = True
        key = "alfred-dev-only-fallback"
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
