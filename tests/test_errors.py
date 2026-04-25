"""Tests for error classification, tracking, and recovery middleware."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from alfred.agent.context import AgentResult
from alfred.agent.errors import (
    ClassifiedError,
    ErrorCategory,
    Severity,
    classify_error,
)
from alfred.agent.error_tracker import ErrorTracker
from alfred.agent.recovery import handle_multi_chain_error, handle_tool_error


# ─── classify_error ────────────────────────────────────────────────


class TestClassifyError:
    def test_postgrest_error(self):
        exc = type("APIError", (Exception,), {"__module__": "postgrest.exceptions"})("connection refused")
        result = classify_error(exc, tool_name="list_contacts")
        assert result.category == ErrorCategory.SUPABASE
        assert result.severity == Severity.TRANSIENT
        assert result.retryable is True
        assert "banco de dados" in result.user_message

    def test_voyage_server_error(self):
        exc = type("ServerError", (Exception,), {"__module__": "voyageai.error"})("500 internal")
        result = classify_error(exc, tool_name="search_memories")
        assert result.category == ErrorCategory.VOYAGE
        assert result.severity == Severity.TRANSIENT
        assert result.retryable is True
        assert "memórias" in result.user_message

    def test_voyage_auth_error(self):
        exc = type("AuthenticationError", (Exception,), {"__module__": "voyageai.error"})("invalid key")
        result = classify_error(exc, tool_name="search_memories")
        assert result.category == ErrorCategory.VOYAGE
        assert result.severity == Severity.FATAL
        assert result.retryable is False

    def test_voyage_invalid_request(self):
        exc = type("InvalidRequestError", (Exception,), {"__module__": "voyageai.error"})("bad input")
        result = classify_error(exc, tool_name="add_memory")
        assert result.category == ErrorCategory.VOYAGE
        assert result.severity == Severity.PERSISTENT
        assert result.retryable is False

    def test_anthropic_error(self):
        exc = type("APIError", (Exception,), {"__module__": "anthropic._exceptions"})("overloaded")
        result = classify_error(exc, tool_name=None)
        assert result.category == ErrorCategory.ANTHROPIC
        assert result.retryable is True

    def test_key_error(self):
        result = classify_error(KeyError("contact_id"), tool_name="update_contact")
        assert result.category == ErrorCategory.TOOL_INPUT
        assert result.severity == Severity.PERSISTENT
        assert result.retryable is False
        assert "contato" in result.user_message

    def test_index_error(self):
        result = classify_error(IndexError("list index out of range"), tool_name="get_contact_digest")
        assert result.category == ErrorCategory.TOOL_INPUT
        assert result.retryable is False

    def test_value_error(self):
        result = classify_error(ValueError("invalid UUID"), tool_name="set_follow_up")
        assert result.category == ErrorCategory.TOOL_INPUT
        assert result.severity == Severity.PERSISTENT
        assert result.retryable is False

    def test_type_error(self):
        result = classify_error(TypeError("missing argument"), tool_name="create_contact")
        assert result.category == ErrorCategory.TOOL_INPUT
        assert result.retryable is False

    def test_unknown_error(self):
        result = classify_error(RuntimeError("something weird"), tool_name="list_contacts")
        assert result.category == ErrorCategory.UNKNOWN
        assert result.severity == Severity.PERSISTENT
        assert result.retryable is False
        assert "problema técnico" in result.user_message

    def test_httpx_connect_error_for_voyage_tool(self):
        exc = type("ConnectError", (Exception,), {"__module__": "httpx._exceptions"})("connection refused")
        result = classify_error(exc, tool_name="search_memories")
        assert result.category == ErrorCategory.VOYAGE
        assert result.retryable is True

    def test_httpx_connect_error_for_db_tool(self):
        exc = type("ConnectError", (Exception,), {"__module__": "httpx._exceptions"})("connection refused")
        result = classify_error(exc, tool_name="list_contacts")
        assert result.category == ErrorCategory.SUPABASE
        assert result.retryable is True

    def test_os_error_for_voyage_tool(self):
        result = classify_error(OSError("network unreachable"), tool_name="add_memory")
        assert result.category == ErrorCategory.VOYAGE
        assert result.retryable is True

    def test_admin_message_includes_details(self):
        result = classify_error(KeyError("missing_field"), tool_name="update_contact")
        assert "update_contact" in result.admin_message
        assert "KeyError" in result.admin_message

    def test_admin_message_truncated(self):
        long_msg = "x" * 500
        result = classify_error(RuntimeError(long_msg), tool_name="test_tool")
        assert len(result.admin_message) < 300


# ─── ErrorTracker ──────────────────────────────────────────────────


class TestErrorTracker:
    @pytest.fixture
    def tracker(self):
        return ErrorTracker()

    def _make_error(self, service: str = "supabase") -> ClassifiedError:
        return ClassifiedError(
            category=ErrorCategory.SUPABASE,
            severity=Severity.TRANSIENT,
            service=service,
            original=RuntimeError("test"),
            user_message="test",
            admin_message="test error",
            retryable=True,
        )

    @pytest.mark.asyncio
    async def test_records_error(self, tracker):
        error = self._make_error()
        await tracker.record(error)
        assert len(tracker._recent) == 1

    @pytest.mark.asyncio
    async def test_no_alert_below_threshold(self, tracker):
        with patch("alfred.agent.error_tracker.ErrorTracker._check_patterns", new_callable=AsyncMock) as mock:
            # Override to actually check — we want to test the real method
            pass

        error = self._make_error()
        with patch("alfred.services.alerts.alert_admin", new_callable=AsyncMock) as mock_alert:
            await tracker.record(error)
            await tracker.record(error)
            mock_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_alert_at_threshold(self, tracker):
        error = self._make_error()
        with patch("alfred.services.alerts.alert_admin", new_callable=AsyncMock) as mock_alert:
            await tracker.record(error)
            await tracker.record(error)
            await tracker.record(error)
            mock_alert.assert_called_once()
            call_text = mock_alert.call_args[0][0]
            assert "supabase" in call_text
            assert "3x" in call_text

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate_alerts(self, tracker):
        error = self._make_error()
        with patch("alfred.services.alerts.alert_admin", new_callable=AsyncMock) as mock_alert:
            for _ in range(6):
                await tracker.record(error)
            assert mock_alert.call_count == 1

    @pytest.mark.asyncio
    async def test_different_services_tracked_separately(self, tracker):
        supabase_error = self._make_error("supabase")
        voyage_error = ClassifiedError(
            category=ErrorCategory.VOYAGE,
            severity=Severity.TRANSIENT,
            service="voyage",
            original=RuntimeError("test"),
            user_message="test",
            admin_message="test error",
            retryable=True,
        )
        with patch("alfred.services.alerts.alert_admin", new_callable=AsyncMock) as mock_alert:
            await tracker.record(supabase_error)
            await tracker.record(supabase_error)
            await tracker.record(voyage_error)
            await tracker.record(voyage_error)
            mock_alert.assert_not_called()


# ─── handle_tool_error ─────────────────────────────────────────────


class TestHandleToolError:
    @pytest.mark.asyncio
    async def test_returns_structured_message(self):
        with patch("alfred.agent.recovery.get_tracker") as mock_tracker:
            mock_tracker.return_value.record = AsyncMock()
            result = await handle_tool_error(
                KeyError("contact_id"), "update_contact"
            )
        assert "ERRO" in result
        assert "TOOL_INPUT" in result
        assert "Não tente chamar" in result

    @pytest.mark.asyncio
    async def test_retryable_hint(self):
        exc = type("ServerError", (Exception,), {"__module__": "voyageai.error"})("500")
        with patch("alfred.agent.recovery.get_tracker") as mock_tracker:
            mock_tracker.return_value.record = AsyncMock()
            result = await handle_tool_error(exc, "search_memories")
        assert "pode tentar chamar" in result

    @pytest.mark.asyncio
    async def test_records_in_tracker(self):
        with patch("alfred.agent.recovery.get_tracker") as mock_tracker:
            mock_tracker.return_value.record = AsyncMock()
            await handle_tool_error(RuntimeError("oops"), "list_contacts")
            mock_tracker.return_value.record.assert_called_once()


# ─── handle_multi_chain_error ──────────────────────────────────────


class TestHandleMultiChainError:
    @pytest.mark.asyncio
    async def test_with_partial_results(self):
        partial = AgentResult(
            text="Contato criado: Pedro Santos",
            tools_called={"create_contact"},
            tool_calls_log=[("create_contact", {"display_name": "Pedro Santos"})],
            created_entities={"Pedro Santos": "uuid-123"},
        )
        with patch("alfred.agent.recovery.get_tracker") as mock_tracker:
            mock_tracker.return_value.record = AsyncMock()
            result = await handle_multi_chain_error(
                RuntimeError("db down"),
                [partial],
                [("create_contact", {"display_name": "Pedro Santos"})],
            )
        assert "Pedro Santos" in result.text
        assert "problema técnico" in result.text
        assert "create_contact" in result.tools_called
        assert result.created_entities["Pedro Santos"] == "uuid-123"

    @pytest.mark.asyncio
    async def test_with_no_partial_results(self):
        with patch("alfred.agent.recovery.get_tracker") as mock_tracker:
            mock_tracker.return_value.record = AsyncMock()
            result = await handle_multi_chain_error(
                RuntimeError("total failure"),
                [],
                [],
            )
        assert "problema técnico" in result.text
        assert not result.tools_called

    @pytest.mark.asyncio
    async def test_records_in_tracker(self):
        with patch("alfred.agent.recovery.get_tracker") as mock_tracker:
            mock_tracker.return_value.record = AsyncMock()
            await handle_multi_chain_error(RuntimeError("fail"), [], [])
            mock_tracker.return_value.record.assert_called_once()
