"""Error classification — deterministic taxonomy for service failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import structlog

log = structlog.get_logger()


class ErrorCategory(Enum):
    SUPABASE = "supabase"
    VOYAGE = "voyage"
    ANTHROPIC = "anthropic"
    TOOL_INPUT = "tool_input"
    UNKNOWN = "unknown"


class Severity(Enum):
    TRANSIENT = "transient"
    PERSISTENT = "persistent"
    FATAL = "fatal"


_USER_MESSAGES: dict[ErrorCategory, str] = {
    ErrorCategory.SUPABASE: (
        "Estou com dificuldade para acessar o banco de dados. "
        "Tente novamente em alguns segundos."
    ),
    ErrorCategory.VOYAGE: (
        "A busca de memórias está temporariamente indisponível. "
        "Posso tentar de novo?"
    ),
    ErrorCategory.ANTHROPIC: (
        "Estou com dificuldade para processar sua solicitação. "
        "Tente novamente em alguns segundos."
    ),
    ErrorCategory.TOOL_INPUT: (
        "Não encontrei o contato ou recurso indicado. "
        "Pode verificar o nome?"
    ),
    ErrorCategory.UNKNOWN: "Tive um problema técnico. Pode tentar de novo? 🙏",
}


@dataclass
class ClassifiedError:
    category: ErrorCategory
    severity: Severity
    service: str
    original: Exception
    user_message: str
    admin_message: str
    retryable: bool


def classify_error(
    exc: Exception, tool_name: str | None = None
) -> ClassifiedError:
    """Classify an exception into a structured error with pre-written messages."""
    exc_type = type(exc).__name__
    exc_module = type(exc).__module__ or ""
    exc_str = str(exc)

    # ─── Supabase / PostgREST / httpx (DB layer) ──────────
    if "postgrest" in exc_module or "APIError" in exc_type and "supabase" in exc_module:
        return ClassifiedError(
            category=ErrorCategory.SUPABASE,
            severity=Severity.TRANSIENT,
            service="supabase",
            original=exc,
            user_message=_USER_MESSAGES[ErrorCategory.SUPABASE],
            admin_message=f"Supabase PostgREST error: {exc_str[:200]}",
            retryable=True,
        )

    if isinstance(exc, OSError) or (
        "httpx" in exc_module
        and any(k in exc_type for k in ("ConnectError", "TimeoutException", "NetworkError"))
    ):
        is_voyage = tool_name in ("search_memories", "add_memory")
        if is_voyage:
            return ClassifiedError(
                category=ErrorCategory.VOYAGE,
                severity=Severity.TRANSIENT,
                service="voyage",
                original=exc,
                user_message=_USER_MESSAGES[ErrorCategory.VOYAGE],
                admin_message=f"Voyage network error: {exc_str[:200]}",
                retryable=True,
            )
        return ClassifiedError(
            category=ErrorCategory.SUPABASE,
            severity=Severity.TRANSIENT,
            service="supabase",
            original=exc,
            user_message=_USER_MESSAGES[ErrorCategory.SUPABASE],
            admin_message=f"Network error ({exc_type}): {exc_str[:200]}",
            retryable=True,
        )

    # ─── Voyage AI ─────────────────────────────────────────
    if "voyageai" in exc_module or "voyage" in exc_module.lower():
        severity = Severity.TRANSIENT
        if "AuthenticationError" in exc_type:
            severity = Severity.FATAL
        elif "InvalidRequestError" in exc_type or "MalformedRequestError" in exc_type:
            severity = Severity.PERSISTENT
        return ClassifiedError(
            category=ErrorCategory.VOYAGE,
            severity=severity,
            service="voyage",
            original=exc,
            user_message=_USER_MESSAGES[ErrorCategory.VOYAGE],
            admin_message=f"Voyage AI {exc_type}: {exc_str[:200]}",
            retryable=severity == Severity.TRANSIENT,
        )

    # ─── Anthropic (fallback — most are caught in base.py) ─
    if "anthropic" in exc_module:
        return ClassifiedError(
            category=ErrorCategory.ANTHROPIC,
            severity=Severity.TRANSIENT,
            service="anthropic",
            original=exc,
            user_message=_USER_MESSAGES[ErrorCategory.ANTHROPIC],
            admin_message=f"Anthropic {exc_type}: {exc_str[:200]}",
            retryable=True,
        )

    # ─── Tool input errors (KeyError, IndexError, ValueError, TypeError) ─
    if isinstance(exc, (KeyError, IndexError, TypeError)):
        return ClassifiedError(
            category=ErrorCategory.TOOL_INPUT,
            severity=Severity.PERSISTENT,
            service=tool_name or "unknown",
            original=exc,
            user_message=_USER_MESSAGES[ErrorCategory.TOOL_INPUT],
            admin_message=f"Tool input error in {tool_name}: {exc_type}: {exc_str[:200]}",
            retryable=False,
        )

    if isinstance(exc, ValueError):
        return ClassifiedError(
            category=ErrorCategory.TOOL_INPUT,
            severity=Severity.PERSISTENT,
            service=tool_name or "unknown",
            original=exc,
            user_message=_USER_MESSAGES[ErrorCategory.TOOL_INPUT],
            admin_message=f"Validation error in {tool_name}: {exc_str[:200]}",
            retryable=False,
        )

    # ─── Unknown ───────────────────────────────────────────
    return ClassifiedError(
        category=ErrorCategory.UNKNOWN,
        severity=Severity.PERSISTENT,
        service=tool_name or "unknown",
        original=exc,
        user_message=_USER_MESSAGES[ErrorCategory.UNKNOWN],
        admin_message=f"Unclassified error in {tool_name}: {exc_type}: {exc_str[:200]}",
        retryable=False,
    )
