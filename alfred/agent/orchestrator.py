"""Orchestrator — multi-agent entry point: context -> route -> select -> run -> save."""

import time

import structlog

from alfred.agent import router
from alfred.agent.agents.activity import ActivityAgent
from alfred.agent.agents.contact import ContactAgent
from alfred.agent.agents.conversation import ConversationAgent
from alfred.agent.agents.drafting import DraftingAgent
from alfred.agent.agents.query import QueryAgent
from alfred.agent.base import BaseAgent
from alfred.agent.context import AgentContext, AgentResult
from alfred.agent.guardrails.date_confirmation import CONFIRMATION_APPROVED
from alfred.agent.history import (
    get_or_create_user,
    load_history,
    save_message,
)

log = structlog.get_logger()

_AGENTS: dict[str, type[BaseAgent]] = {
    "QUERY": QueryAgent,
    "CONTACT": ContactAgent,
    "RECORD": ActivityAgent,
    "DRAFT": DraftingAgent,
    "CONVERSATION": ConversationAgent,
}


def _select_agent(intent: str) -> BaseAgent:
    cls = _AGENTS.get(intent, ActivityAgent)
    return cls()


async def run_agent(telegram_id: int, user_name: str, message: str) -> str:
    """Multi-agent entry point. Drop-in replacement for loop.run_agent."""
    user_id = await get_or_create_user(telegram_id, user_name)

    from alfred.services.limits import check_message_limit

    allowed, reason = await check_message_limit(user_id)
    if not allowed:
        return reason

    history = await load_history(user_id)

    history.append({"role": "user", "content": message})
    await save_message(user_id, "user", message)

    ctx = AgentContext(
        user_id=user_id,
        telegram_id=telegram_id,
        user_name=user_name,
        message=message,
        current_date=AgentContext.make_date_str(),
        is_confirmation=message.startswith(CONFIRMATION_APPROVED),
        history=history,
    )

    if ctx.is_confirmation:
        log.info("orchestrator.confirmation_bypass")
        result = await ActivityAgent().run(ctx)
        await save_message(user_id, "assistant", result.text)
        return result.text

    route = await router.classify(message)
    ctx.intent = route.intent

    log.info(
        "orchestrator.routed",
        intent=route.intent,
        confidence=route.confidence,
        agents=route.agents,
    )

    t0 = time.monotonic()

    if route.intent == "MULTI":
        result = await _run_multi(ctx, route.agents)
    else:
        agent = _select_agent(route.intent)
        log.info("orchestrator.agent_selected", agent=type(agent).__name__)
        result = await agent.run(ctx)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log.info(
        "orchestrator.done",
        intent=route.intent,
        tools_called=sorted(result.tools_called),
        elapsed_ms=elapsed_ms,
    )

    await save_message(user_id, "assistant", result.text)
    return result.text


async def _run_multi(ctx: AgentContext, agent_intents: list[str]) -> AgentResult:
    """Execute multiple agents sequentially, propagating context between them."""
    from alfred.agent.recovery import handle_multi_chain_error

    results: list[AgentResult] = []

    for intent in agent_intents:
        agent = _select_agent(intent)
        log.info("orchestrator.multi_step", intent=intent, agent=type(agent).__name__)
        try:
            result = await agent.run(ctx)
        except Exception as exc:
            return await handle_multi_chain_error(
                exc, results, ctx.tool_calls_log,
            )
        results.append(result)

        ctx.tools_called.update(result.tools_called)
        ctx.tool_calls_log.extend(result.tool_calls_log)
        ctx.created_entities.update(result.created_entities)

        if result.text:
            ctx.history.append({"role": "assistant", "content": result.text})

    return _combine_responses(results)


def _combine_responses(results: list[AgentResult]) -> AgentResult:
    """Merge responses from multiple agents into a single result."""
    texts = [r.text for r in results if r.text]
    all_tools = set()
    all_log: list[tuple[str, dict]] = []
    all_entities: dict[str, str] = {}

    for r in results:
        all_tools.update(r.tools_called)
        all_log.extend(r.tool_calls_log)
        all_entities.update(r.created_entities)

    return AgentResult(
        text="\n\n".join(texts),
        tools_called=all_tools,
        tool_calls_log=all_log,
        created_entities=all_entities,
    )
