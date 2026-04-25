"""Agent loop with tool use."""
import asyncio

import structlog
from anthropic import APIConnectionError, APIStatusError, RateLimitError
from anthropic.types import TextBlock, ToolResultBlockParam, ToolUseBlock

from alfred.agent.classifier import classify_intent
from alfred.agent.client import MAX_TOKENS, MODEL, get_anthropic
from alfred.agent.guardrails.date_confirmation import (
    CONFIRMATION_APPROVED,
    is_date_confirmation_prompt,
)
from alfred.agent.guardrails.pending_actions import detect_pending_actions
from alfred.agent.guardrails.truthfulness import validate_response_truthfulness
from alfred.agent.history import (
    alert_owner,
    build_partial_report,
    get_or_create_user,
    load_history,
    save_message,
)
from alfred.agent.prompt_sections import build_system_prompt
from alfred.agent.prompts import SYSTEM_PROMPT  # noqa: F401 — kept as fallback reference
from alfred.agent.recovery import handle_tool_error
from alfred.agent.tools import TOOL_SCHEMAS, dispatch_tool, get_tools_for_intent
from alfred.services.alerts import alert_admin
from alfred.services.usage import record_usage

log = structlog.get_logger()

_CONFIRMATION_APPROVED = CONFIRMATION_APPROVED


async def run_agent(telegram_id: int, user_name: str, message: str) -> str:
    """Run one agent turn. Returns the text response."""
    from datetime import datetime, timedelta, timezone
    brt = timezone(timedelta(hours=-3))
    now = datetime.now(brt)
    current_date_str = now.strftime("%Y-%m-%d (%A, %H:%M BRT)")

    user_id = await get_or_create_user(telegram_id, user_name)
    history = await load_history(user_id)

    # Append new user message
    history.append({"role": "user", "content": message})
    await save_message(user_id, "user", message)

    client = get_anthropic()
    messages = list(history)

    # Classify intent (skip for confirmation responses)
    is_confirmation = message.startswith(_CONFIRMATION_APPROVED)
    if is_confirmation:
        intent_name = "ACTION"
    else:
        intent_result = await classify_intent(message)
        intent_name = intent_result.intent
        log.info("agent.intent", intent=intent_name, confidence=intent_result.confidence)

    # Build scoped prompt and tools
    system_prompt = build_system_prompt(intent_name, current_date_str)
    tools = get_tools_for_intent(intent_name)

    # Guardrail routing by intent
    skip_pending_guardrail = is_confirmation or intent_name in ("QUERY", "CONVERSATION")
    if not skip_pending_guardrail:
        for m in reversed(history[:-1]):
            if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                skip_pending_guardrail = is_date_confirmation_prompt(m["content"])
                break

    # Tracks every tool name executed neste turno — usado pelo guardrail
    tools_called_this_turn: set[str] = set()
    # Log completo (nome + input) — usado pelo validador de veracidade
    tool_calls_log: list[tuple[str, dict]] = []
    # Quantas vezes o pending-actions guardrail reinjetou lembrete (evita loop infinito).
    pending_retries = 0
    MAX_PENDING_RETRIES = 2
    # Quando True, força tool_choice=any no próximo round para quebrar
    # alucinações em que Claude insiste em emitir texto sem chamar ferramentas
    force_tool_use_next_round = False
    rate_limit_retries = 0

    # Agentic loop — keep going until we get a stop_turn with no tool calls
    for _turn in range(15):  # max 15 tool rounds
        try:
            create_kwargs: dict = {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": messages,
            }
            active_tools = tools or TOOL_SCHEMAS
            if active_tools:
                create_kwargs["tools"] = active_tools
            if force_tool_use_next_round:
                create_kwargs["tool_choice"] = {"type": "any"}
                force_tool_use_next_round = False
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
                return (
                    "Estou com limitação de taxa. O que já foi feito:\n"
                    f"{partial}\n\n"
                    "Tente novamente em alguns minutos para completar o restante. 🔄"
                )
        except APIStatusError as exc:
            log.error("anthropic.api_error", status=exc.status_code)
            if exc.status_code == 402:
                await alert_admin(
                    "❌ *Créditos Anthropic ESGOTADOS*\n\n"
                    "O Alfred parou de responder.\n"
                    "Recarregue: console.anthropic.com"
                )
                return "Estou temporariamente fora do ar. O administrador já foi notificado. 🔧"
            return "Ocorreu um erro no servidor, tente novamente. 🛠️"
        except APIConnectionError:
            log.error("anthropic.connection_error")
            return "Não consegui conectar ao servidor, tente novamente. 🔌"

        log.info(
            "agent.response",
            stop_reason=response.stop_reason,
            usage=response.usage.model_dump(),
        )

        usage = response.usage
        await record_usage(
            model=MODEL,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            user_id=user_id,
        )

        # Collect tool calls from this response
        tool_calls = [b for b in response.content if isinstance(b, ToolUseBlock)]
        text_blocks = [b for b in response.content if isinstance(b, TextBlock)]

        if response.stop_reason == "end_turn" or not tool_calls:
            # ───── Bypass legítimo: proposta de confirmação de data ─────
            preview_text = "\n".join(b.text for b in text_blocks).strip()
            if is_date_confirmation_prompt(preview_text):
                log.info(
                    "guardrail.date_confirmation_bypass",
                    preview=preview_text[:240],
                    tools_called=list(tools_called_this_turn),
                )
                await save_message(user_id, "assistant", preview_text)
                return preview_text

            # ───── Guardrail: verifica ferramentas pendentes ─────
            missing = (
                detect_pending_actions(message, tools_called_this_turn)
                if not skip_pending_guardrail
                else []
            )
            if missing and pending_retries < MAX_PENDING_RETRIES:
                pending_retries += 1
                log.warning(
                    "guardrail.pending_actions",
                    missing=missing,
                    tools_called=list(tools_called_this_turn),
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
                messages.append({"role": "assistant", "content": response.content})  # type: ignore[typeddict-item]
                messages.append({"role": "user", "content": reminder_text})
                force_tool_use_next_round = True
                continue

            # Guardrail esgotou retries mas ainda detecta ferramenta faltando
            if missing:
                log.error(
                    "guardrail.exhausted",
                    missing=missing,
                    tools_called=list(tools_called_this_turn),
                )
                error_msg = (
                    "Ops, travou aqui e não consegui executar tudo o que você pediu. "
                    "Pode confirmar o que você quer que eu faça? Vou refazer com cuidado. 🙏"
                )
                await save_message(user_id, "assistant", error_msg)
                return error_msg

            # Final answer (candidato)
            final_text = "\n".join(b.text for b in text_blocks).strip()
            if not final_text:
                final_text = "Feito."

            # ───── Validador de veracidade — observabilidade, não bloqueante ─────
            truthfulness_problems = await validate_response_truthfulness(
                user_id=user_id,
                final_text=final_text,
                tool_calls_log=tool_calls_log,
            )
            if truthfulness_problems:
                log.warning(
                    "validator.truthfulness_issues",
                    problems=truthfulness_problems,
                    tools_called=list(tools_called_this_turn),
                )

            # Save assistant message
            await save_message(user_id, "assistant", final_text)
            return final_text

        # ───── Guardrail: bloqueia tools de data sem confirmação prévia ─────
        _DATE_TOOLS = {"set_follow_up", "log_interaction"}
        date_tools_requested = [tc for tc in tool_calls if tc.name in _DATE_TOOLS]
        if date_tools_requested and not skip_pending_guardrail:
            log.warning(
                "guardrail.date_tool_without_confirmation",
                tools=[tc.name for tc in date_tools_requested],
            )
            skip_pending_guardrail = True

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
                    tools_called_this_turn.add(tool_call.name)
                    tool_calls_log.append((tool_call.name, dict(tool_call.input)))  # type: ignore[arg-type]
                    try:
                        result = await dispatch_tool(
                            tool_name=tool_call.name,
                            tool_input=dict(tool_call.input),  # type: ignore[arg-type]
                            user_id=user_id,
                        )
                    except Exception as exc:
                        result = await handle_tool_error(exc, tool_call.name)
                    blocked_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": result,
                    })
            messages.append({"role": "assistant", "content": response.content})  # type: ignore[typeddict-item]
            messages.append({"role": "user", "content": blocked_results})  # type: ignore[typeddict-item]
            continue

        # Execute tool calls
        tool_results: list[ToolResultBlockParam] = []
        for tool_call in tool_calls:
            tools_called_this_turn.add(tool_call.name)
            tool_calls_log.append((tool_call.name, dict(tool_call.input)))  # type: ignore[arg-type]
            try:
                result = await dispatch_tool(
                    tool_name=tool_call.name,
                    tool_input=dict(tool_call.input),  # type: ignore[arg-type]
                    user_id=user_id,
                )
            except Exception as exc:
                result = await handle_tool_error(exc, tool_call.name)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": result,
            })

        # Add assistant turn + tool results to messages
        messages.append({"role": "assistant", "content": response.content})  # type: ignore[typeddict-item]
        messages.append({"role": "user", "content": tool_results})  # type: ignore[typeddict-item]

    if tool_calls_log:
        partial = build_partial_report(tool_calls_log)
        fallback = (
            f"Consegui fazer parte do que você pediu:\n{partial}\n\n"
            "A mensagem era longa — pode repetir o que ficou faltando? 🙏"
        )
    else:
        fallback = "Não consegui completar a solicitação. Pode tentar de novo com menos itens? 🙏"
    await save_message(user_id, "assistant", fallback)
    return fallback
