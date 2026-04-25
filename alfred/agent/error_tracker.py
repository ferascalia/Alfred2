"""Error pattern detection — alerts admin when a service fails repeatedly."""

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timedelta, timezone

import structlog

from alfred.agent.errors import ClassifiedError

log = structlog.get_logger()

_WINDOW_MINUTES = 30
_ALERT_THRESHOLD = 3
_COOLDOWN_MINUTES = 60

UTC = timezone.utc


class ErrorTracker:
    """In-memory tracker that detects repeated failures and alerts admin."""

    def __init__(self) -> None:
        self._recent: deque[tuple[datetime, ClassifiedError]] = deque()
        self._last_alert: dict[str, datetime] = {}

    async def record(self, error: ClassifiedError) -> None:
        now = datetime.now(UTC)
        self._recent.append((now, error))
        self._prune(now)

        log.error(
            "error_tracker.recorded",
            category=error.category.value,
            severity=error.severity.value,
            service=error.service,
            retryable=error.retryable,
            admin_message=error.admin_message,
        )

        await self._check_patterns(now)

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(minutes=_WINDOW_MINUTES)
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()

    async def _check_patterns(self, now: datetime) -> None:
        counts = Counter(e.service for _, e in self._recent)

        for service, count in counts.items():
            if count < _ALERT_THRESHOLD:
                continue

            last = self._last_alert.get(service)
            if last and (now - last) < timedelta(minutes=_COOLDOWN_MINUTES):
                continue

            self._last_alert[service] = now
            log.warning(
                "error_tracker.pattern_detected",
                service=service,
                count=count,
                window_minutes=_WINDOW_MINUTES,
            )

            last_error = next(
                (e for _, e in reversed(self._recent) if e.service == service),
                None,
            )
            admin_detail = last_error.admin_message if last_error else "unknown"

            try:
                from alfred.services.alerts import alert_admin

                await alert_admin(
                    f"⚠️ *Alerta de Erro Alfred*\n\n"
                    f"Serviço `{service}` falhou {count}x nos últimos {_WINDOW_MINUTES} min.\n"
                    f"Último erro: {admin_detail}"
                )
            except Exception:
                log.exception("error_tracker.alert_failed", service=service)


_tracker: ErrorTracker | None = None


def get_tracker() -> ErrorTracker:
    global _tracker
    if _tracker is None:
        _tracker = ErrorTracker()
    return _tracker
