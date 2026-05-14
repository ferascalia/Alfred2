"""Tests for orchestrator bypass routing of scheduling choice markers."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture(autouse=True)
def _mock_deps():
    with patch("alfred.agent.orchestrator.get_or_create_user", AsyncMock(return_value="user-1")), \
         patch("alfred.agent.orchestrator.load_history", AsyncMock(return_value=[])), \
         patch("alfred.agent.orchestrator.save_message", AsyncMock()), \
         patch("alfred.services.access.check_access", AsyncMock(return_value=True)), \
         patch("alfred.services.limits.check_message_limit", AsyncMock(return_value=(True, ""))):
        yield


@pytest.mark.asyncio
async def test_scheduling_choice_calendar_bypasses_to_activity_agent() -> None:
    from alfred.agent.orchestrator import run_agent

    with patch("alfred.agent.orchestrator.ActivityAgent") as MockActivity:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = MagicMock(text="Agendando:\n• Hugo — 14/05/2026 às 17:00")
        MockActivity.return_value = mock_agent

        result = await run_agent(
            telegram_id=123,
            user_name="Test",
            message="[ESCOLHA AGENDA: calendar] Escolha como agendar:\n• Hugo — 14/05/2026 às 17:00",
        )

        mock_agent.run.assert_called_once()
        assert "Hugo" in result


@pytest.mark.asyncio
async def test_scheduling_choice_followup_bypasses_to_activity_agent() -> None:
    from alfred.agent.orchestrator import run_agent

    with patch("alfred.agent.orchestrator.ActivityAgent") as MockActivity:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = MagicMock(text="Confirmando:\n• Hugo — follow-up 14/05/2026 às 17:00")
        MockActivity.return_value = mock_agent

        result = await run_agent(
            telegram_id=123,
            user_name="Test",
            message="[ESCOLHA AGENDA: followup] Escolha como agendar:\n• Hugo — 14/05/2026 às 17:00",
        )

        mock_agent.run.assert_called_once()
        assert "Hugo" in result


@pytest.mark.asyncio
async def test_reminder_also_bypasses_to_activity_agent() -> None:
    from alfred.agent.orchestrator import run_agent

    with patch("alfred.agent.orchestrator.ActivityAgent") as MockActivity:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = MagicMock(text="Follow-up criado com Hugo.")
        MockActivity.return_value = mock_agent

        result = await run_agent(
            telegram_id=123,
            user_name="Test",
            message="[LEMBRETE TAMBÉM: sim] Crie também um follow-up.",
        )

        mock_agent.run.assert_called_once()
        assert "Hugo" in result
