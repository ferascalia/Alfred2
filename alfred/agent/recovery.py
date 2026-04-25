"""Recovery middleware — structured error handling for tool calls and MULTI chains."""

from __future__ import annotations

import structlog

from alfred.agent.context import AgentResult
from alfred.agent.errors import ClassifiedError, classify_error
from alfred.agent.error_tracker import get_tracker
from alfred.agent.history import build_partial_report

log = structlog.get_logger()


async def handle_tool_error(exc: Exception, tool_name: str) -> str:
    """Classify error, record in tracker, return structured message for Claude."""
    classified = classify_error(exc, tool_name=tool_name)

    log.error(
        "tool.error.classified",
        tool=tool_name,
        category=classified.category.value,
        severity=classified.severity.value,
        retryable=classified.retryable,
    )

    await get_tracker().record(classified)

    retry_hint = (
        " Você pode tentar chamar esta ferramenta novamente."
        if classified.retryable
        else " Não tente chamar esta ferramenta novamente com os mesmos parâmetros."
    )

    return (
        f"ERRO [{classified.category.value.upper()}]: "
        f"{classified.user_message}{retry_hint}"
    )


async def handle_multi_chain_error(
    exc: Exception,
    results_so_far: list[AgentResult],
    tool_calls_log: list[tuple[str, dict]],
) -> AgentResult:
    """Salvage partial results from a MULTI chain when one agent fails."""
    classified = classify_error(exc)

    log.error(
        "orchestrator.multi_chain_error",
        category=classified.category.value,
        severity=classified.severity.value,
        completed_agents=len(results_so_far),
    )

    await get_tracker().record(classified)

    if results_so_far:
        partial_text = "\n\n".join(r.text for r in results_so_far if r.text)
        partial_report = build_partial_report(tool_calls_log)

        all_tools = set()
        all_log: list[tuple[str, dict]] = []
        all_entities: dict[str, str] = {}
        for r in results_so_far:
            all_tools.update(r.tools_called)
            all_log.extend(r.tool_calls_log)
            all_entities.update(r.created_entities)

        text = (
            f"{partial_text}\n\n"
            f"{classified.user_message}\n\n"
            f"O que já foi feito:\n{partial_report}"
        )

        return AgentResult(
            text=text,
            tools_called=all_tools,
            tool_calls_log=all_log,
            created_entities=all_entities,
        )

    return AgentResult(text=classified.user_message)
