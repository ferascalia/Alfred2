"""BaseAgent — abstract base class for all specialist agents."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog
from anthropic import APIConnectionError, APIStatusError, RateLimitError
from anthropic.types import TextBlock, ToolResultBlockParam, ToolUseBlock

from alfred.agent.client import get_anthropic
from alfred.agent.context import AgentContext, AgentResult
from alfred.agent.guardrails.date_confirmation import is_date_confirmation_prompt
from alfred.agent.guardrails.pending_actions import detect_pending_actions
from alfred.agent.guardrails.truthfulness import validate_response_truthfulness
from alfred.agent.history import build_partial_report
from alfred.agent.recovery import handle_tool_error
from alfred.agent.tools.dispatch import dispatch_tool
from alfred.services.alerts import alert_admin
from alfred.services.usage import record_usage

log = structlog.get_logger()

MAX_TOOL_ROUNDS = 15
MAX_PENDING_RETRIES = 2


@dataclass(frozen=True)
class GuardrailConfig:
    """Declares which guardrails an agent activates."""
    pending_actions: bool = False
    date_confirmation: bool = False
    truthfulness: bool = False


class BaseAgent(ABC):
    """Abstract base for all specialist agents.

    Subclasses define model, tools, guardrails, and prompt.
    The agentic loop (run) is generic and shared.
    """

    model: str
    max_tokens: int
    guardrail_config: GuardrailConfig

    @abstractmethod
    def get_tools(self) -> list[dict[str, Any]]:
        """Return the tool schemas this agent can use."""

    @abstractmethod
    def build_prompt(self, ctx: AgentContext) -> str:
        """Build the system prompt for this agent."""

    async def run(self, ctx: AgentContext) -> AgentResult:
        """Execute the agentic loop: API call -> tool dispatch -> guardrails -> response."""
        client = get_anthropic()
        messages: list[dict[str, Any]] = list(ctx.history)
        tools = self.get_tools()
        system_prompt = self.build_prompt(ctx)

        tools_called: set[str] = set()
        tool_calls_log: list[tuple[str, dict]] = []
        pending_retries = 0
        force_tool_use = False
        rate_limit_retries = 0

        skip_pending = ctx.is_confirmation or not self.guardrail_config.pending_actions

        if not skip_pending:
            for m in reversed(ctx.history[:-1]):
                if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                    skip_pending = is_date_confirmation_prompt(m["content"])
                    break

        for _turn in range(MAX_TOOL_ROUNDS):
            # ─── API call ─────────────────────────────────────
            try:
                create_kwargs: dict = {
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "system": [
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    "messages": messages,
                }
                if tools:
                    create_kwargs["tools"] = tools
                if force_tool_use:
                    create_kwargs["tool_choice"] = {"type": "any"}
                    force_tool_use = False
                response = await client.messages.create(**create_kwargs)
            except RateLimitError:
                if rate_limit_retries < 2:
                    rate_limit_retries += 1
                    log.warning("anthropic.rate_limit_retry", attempt=rate_limit_retries)
                    await asyncio.sleep(5 * rate_limit_retries)
                    continue
                log.warning("anthropic.rate_limit_exhausted")
                if tool_calls_log:
                    partial = build_partial_report(tool_calls_log)
                    return AgentResult(
                        text=(
                            "Estou com limitação de taxa. O que já foi feito:\n"
                            f"{partial}\n\n"
                            "Tente novamente em alguns minutos para completar o restante. 🔄"
                        ),
                        tools_called=tools_called,
                        tool_calls_log=tool_calls_log,
                    )
                return AgentResult(text="Estou com limitação de taxa. Tente novamente em alguns minutos. 🔄")
            except APIStatusError as exc:
                log.error("anthropic.api_error", status=exc.status_code)
                if exc.status_code == 402:
                    await alert_admin(
                        "❌ *Créditos Anthropic ESGOTADOS*\n\n"
                        "O Alfred parou de responder.\n"
                        "Recarregue: console.anthropic.com"
                    )
                    return AgentResult(text="Estou temporariamente fora do ar. O administrador já foi notificado. 🔧")
                return AgentResult(text="Ocorreu um erro no servidor, tente novamente. 🛠️")
            except APIConnectionError:
                log.error("anthropic.connection_error")
                return AgentResult(text="Não consegui conectar ao servidor, tente novamente. 🔌")

            log.info(
                "agent.response",
                stop_reason=response.stop_reason,
                usage=response.usage.model_dump(),
            )

            usage = response.usage
            await record_usage(
                model=self.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                user_id=ctx.user_id,
            )

            tool_calls = [b for b in response.content if isinstance(b, ToolUseBlock)]
            text_blocks = [b for b in response.content if isinstance(b, TextBlock)]

            # ─── Final answer (no tool calls) ─────────────────
            if response.stop_reason == "end_turn" or not tool_calls:
                preview_text = "\n".join(b.text for b in text_blocks).strip()

                # Date confirmation bypass
                if self.guardrail_config.date_confirmation and is_date_confirmation_prompt(preview_text):
                    log.info(
                        "guardrail.date_confirmation_bypass",
                        preview=preview_text[:240],
                        tools_called=list(tools_called),
                    )
                    return AgentResult(
                        text=preview_text,
                        tools_called=tools_called,
                        tool_calls_log=tool_calls_log,
                    )

                # Pending-actions guardrail
                missing = (
                    detect_pending_actions(ctx.message, tools_called)
                    if not skip_pending
                    else []
                )
                if missing and pending_retries < MAX_PENDING_RETRIES:
                    pending_retries += 1
                    log.warning(
                        "guardrail.pending_actions",
                        missing=missing,
                        tools_called=list(tools_called),
                        retry=pending_retries,
                    )
                    reminder_text = (
                        "⚠️ STOP. IGNORE qualquer confirmação anterior no histórico — aquilo pode "
                        "ser alucinação de turno passado. Verifique APENAS o que foi executado "
                        "neste turno atual via ferramentas.\n\n"
                        "Faltam ferramentas a chamar para cumprir a mensagem atual do usuário:\n\n"
                        + "\n".join(missing)
                        + "\n\nExecute essas ferramentas AGORA. Se precisar do contact_id, chame "
                        "list_contacts primeiro. Se o contato não existir, chame create_contact. "
                        "NÃO emita texto final até que todas as ações tenham sido realmente realizadas."
                    )
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({"role": "user", "content": reminder_text})
                    force_tool_use = True
                    continue

                if missing:
                    log.error(
                        "guardrail.exhausted",
                        missing=missing,
                        tools_called=list(tools_called),
                    )
                    return AgentResult(
                        text=(
                            "Ops, travou aqui e não consegui executar tudo o que você pediu. "
                            "Pode confirmar o que você quer que eu faça? Vou refazer com cuidado. 🙏"
                        ),
                        tools_called=tools_called,
                        tool_calls_log=tool_calls_log,
                    )

                final_text = preview_text or "Feito."

                # Truthfulness guardrail
                if self.guardrail_config.truthfulness:
                    problems = await validate_response_truthfulness(
                        user_id=ctx.user_id,
                        final_text=final_text,
                        tool_calls_log=tool_calls_log,
                    )
                    if problems:
                        log.warning(
                            "validator.truthfulness_issues",
                            problems=problems,
                            tools_called=list(tools_called),
                        )

                return AgentResult(
                    text=final_text,
                    tools_called=tools_called,
                    tool_calls_log=tool_calls_log,
                )

            # ─── Date-tool blocking guardrail ─────────────────
            _DATE_TOOLS = {"set_follow_up", "log_interaction"}
            date_tools_requested = [tc for tc in tool_calls if tc.name in _DATE_TOOLS]

            if date_tools_requested and self.guardrail_config.date_confirmation and not skip_pending:
                log.warning(
                    "guardrail.date_tool_without_confirmation",
                    tools=[tc.name for tc in date_tools_requested],
                )
                skip_pending = True

                blocked_results: list[ToolResultBlockParam] = []
                attempted_dates: list[str] = []
                for tc in date_tools_requested:
                    inp = dict(tc.input)  # type: ignore[arg-type]
                    d = inp.get("date") or inp.get("happened_at") or ""
                    if d:
                        attempted_dates.append(d)
                date_hint = ""
                if attempted_dates:
                    formatted = ", ".join(attempted_dates)
                    date_hint = f" As datas que você calculou ({formatted}) estão corretas — inclua-as no formato DD/MM/AAAA."

                for tool_call in tool_calls:
                    if tool_call.name in _DATE_TOOLS:
                        blocked_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": (
                                "BLOQUEADO: esta ferramenta só pode ser chamada DEPOIS que o "
                                "usuário confirmar a data via botão ✅. Responda APENAS com texto "
                                "(sem chamar nenhuma ferramenta) começando com a palavra "
                                "'Confirmando:' seguida das datas no formato DD/MM/AAAA. "
                                "Exemplo: 'Confirmando: follow-up do Fulano para 23/04/2026 (quarta)?'"
                                f"{date_hint} "
                                "NÃO chame esta ferramenta novamente até receber "
                                "'[CONFIRMAÇÃO APROVADA]'."
                            ),
                            "is_error": True,
                        })
                    else:
                        tools_called.add(tool_call.name)
                        tool_calls_log.append((tool_call.name, dict(tool_call.input)))  # type: ignore[arg-type]
                        try:
                            result = await dispatch_tool(
                                tool_name=tool_call.name,
                                tool_input=dict(tool_call.input),  # type: ignore[arg-type]
                                user_id=ctx.user_id,
                            )
                        except Exception as exc:
                            result = await handle_tool_error(exc, tool_call.name)
                        blocked_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": result,
                        })
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": blocked_results})
                continue

            # ─── Execute tool calls ───────────────────────────
            tool_results: list[ToolResultBlockParam] = []
            for tool_call in tool_calls:
                tools_called.add(tool_call.name)
                tool_calls_log.append((tool_call.name, dict(tool_call.input)))  # type: ignore[arg-type]
                try:
                    result = await dispatch_tool(
                        tool_name=tool_call.name,
                        tool_input=dict(tool_call.input),  # type: ignore[arg-type]
                        user_id=ctx.user_id,
                    )
                except Exception as exc:
                    log.exception("tool.error", tool=tool_call.name)
                    result = f"Erro ao executar ferramenta: {exc}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result,
                })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        # Loop exhausted
        if tool_calls_log:
            partial = build_partial_report(tool_calls_log)
            text = (
                f"Consegui fazer parte do que você pediu:\n{partial}\n\n"
                "A mensagem era longa — pode repetir o que ficou faltando? 🙏"
            )
        else:
            text = "Não consegui completar a solicitação. Pode tentar de novo com menos itens? 🙏"
        return AgentResult(
            text=text,
            tools_called=tools_called,
            tool_calls_log=tool_calls_log,
        )
