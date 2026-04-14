"""Agent loop with tool use."""
import re

import structlog
from anthropic import APIConnectionError, APIStatusError, RateLimitError
from anthropic.types import MessageParam, TextBlock, ToolResultBlockParam, ToolUseBlock

from alfred.agent.client import MAX_TOKENS, MODEL, get_anthropic
from alfred.agent.prompts import SYSTEM_PROMPT
from alfred.agent.tools import TOOL_SCHEMAS, dispatch_tool
from alfred.db.client import get_db

log = structlog.get_logger()


# ───────────────────────────────────────────────────────────────
# Guardrail determinístico — detecta ações pendentes não executadas
# ───────────────────────────────────────────────────────────────

# Verbos que indicam que o usuário falou/encontrou/interagiu com alguém
_INTERACTION_PATTERNS = [
    r"\bfalei\b", r"\bfalamos\b", r"\bconvers(ei|amos|ando)\b",
    r"\bencontr(ei|amos|ou)\b", r"\bligu(ei|ou)\b", r"\balmo(c|ç)(ei|amos)\b",
    r"\bjant(ei|amos)\b", r"\bvi\s+(o|a|ele|ela)\b", r"\breun(i|imos)\b",
    r"\bmandou\b", r"\bmandei\b", r"\bme\s+ligou\b", r"\bme\s+chamou\b",
]

# Patterns que indicam follow-up, prazo ou data futura
_FOLLOWUP_PATTERNS = [
    r"\bme\s+lembr(a|e|ar)\b", r"\bmarc(a|ar|e)\b", r"\bagend(a|ar|e)\b",
    r"\breagend(a|ar|e)\b", r"\bfollow[\s-]?up\b", r"\bamanh(ã|a)\b",
    r"\bdepois\s+de\s+amanh(ã|a)\b", r"\bsemana\s+que\s+vem\b",
    r"\bpr(ó|o)xim(a|o)\s+(semana|mês|mes)\b",
    r"\b(segunda|ter(ç|c)a|quarta|quinta|sexta|s(á|a)bado|domingo)(-feira)?\b",
    r"\bdaqui\s+a\s+\d+\s+dias?\b", r"\bem\s+\d+\s+dias?\b",
]

# Patterns para cadência recorrente
_CADENCE_PATTERNS = [
    r"\btoda\s+(segunda|ter(ç|c)a|quarta|quinta|sexta|s(á|a)bado|domingo)",
    r"\ba\s+cada\s+\d+\s+dias?\b", r"\bde\s+\d+\s+em\s+\d+\s+dias?\b",
    r"\bsemanalmente\b", r"\bmensalmente\b",
]


def _detect_pending_actions(user_message: str, tools_called: set[str]) -> list[str]:
    """Retorna lista de lembretes para ferramentas esperadas mas não chamadas."""
    msg = user_message.lower()
    missing: list[str] = []

    has_interaction = any(re.search(p, msg) for p in _INTERACTION_PATTERNS)
    has_followup = any(re.search(p, msg) for p in _FOLLOWUP_PATTERNS)
    has_cadence = any(re.search(p, msg) for p in _CADENCE_PATTERNS)

    if has_interaction and "log_interaction" not in tools_called:
        missing.append(
            "• `log_interaction` — você mencionou ter falado/encontrado/conversado com a pessoa, "
            "mas não registrou a interação."
        )

    # Follow-up e cadência são excludentes: basta uma das duas ferramentas
    needs_scheduling = has_followup or has_cadence
    scheduled = "set_follow_up" in tools_called or "set_cadence" in tools_called
    if needs_scheduling and not scheduled:
        if has_cadence:
            missing.append(
                "• `set_cadence` — você pediu cadência recorrente mas não configurou."
            )
        else:
            missing.append(
                "• `set_follow_up` — você mencionou um prazo, data futura ou 'me lembra' "
                "mas não agendou o follow-up. Calcule a data absoluta (YYYY-MM-DD) a partir de hoje."
            )

    return missing


async def _alert_owner(telegram_id: int, message: str) -> None:
    """Send an urgent alert to the user via Telegram."""
    try:
        from telegram import Bot
        from alfred.config import settings
        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(chat_id=telegram_id, text=message, parse_mode="Markdown")
    except Exception:
        log.exception("alert.failed", telegram_id=telegram_id)


async def _get_or_create_user(telegram_id: int, user_name: str) -> str:
    """Return the internal user UUID for a Telegram user."""
    db = get_db()
    result = (
        db.table("users")
        .upsert(
            {
                "telegram_id": telegram_id,
                "name": user_name,
                "timezone": "America/Sao_Paulo",
                "locale": "pt-BR",
            },
            on_conflict="telegram_id",
        )
        .execute()
    )
    return result.data[0]["id"]


async def _load_history(user_id: str, limit: int = 20) -> list[MessageParam]:
    """Load recent conversation messages from DB."""
    db = get_db()

    conv_result = (
        db.table("conversations")
        .select("id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not conv_result.data:
        return []

    conv_id = conv_result.data[0]["id"]
    msgs_result = (
        db.table("messages")
        .select("role, content")
        .eq("conversation_id", conv_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    messages: list[MessageParam] = []
    for row in reversed(msgs_result.data):
        messages.append({"role": row["role"], "content": row["content"]})  # type: ignore[typeddict-item]
    return messages


async def _save_message(user_id: str, role: str, content: object) -> None:
    db = get_db()

    # Get or create conversation
    conv_result = (
        db.table("conversations")
        .select("id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if conv_result.data:
        conv_id = conv_result.data[0]["id"]
        db.table("conversations").update({"last_message_at": "now()"}).eq("id", conv_id).execute()
    else:
        new_conv = db.table("conversations").insert({"user_id": user_id, "telegram_chat_id": 0}).execute()
        conv_id = new_conv.data[0]["id"]

    db.table("messages").insert({
        "conversation_id": conv_id,
        "role": role,
        "content": content,
    }).execute()


async def run_agent(telegram_id: int, user_name: str, message: str) -> str:
    """Run one agent turn. Returns the text response."""
    from datetime import datetime, timezone, timedelta
    brt = timezone(timedelta(hours=-3))
    now = datetime.now(brt)
    current_date_str = now.strftime("%Y-%m-%d (%A, %H:%M BRT)")  # ex: "2026-04-12 (Sunday, 08:30 BRT)"
    system_prompt = SYSTEM_PROMPT + f"\n\n## Data e hora atual\nHoje é {current_date_str}. Use sempre esta data/hora como referência ao registrar interações (happened_at) ou calcular follow-ups. Nunca use datas do passado para happened_at — use a data de hoje salvo o usuário dizer explicitamente outra."

    user_id = await _get_or_create_user(telegram_id, user_name)
    history = await _load_history(user_id)

    # Append new user message
    history.append({"role": "user", "content": message})
    await _save_message(user_id, "user", message)

    client = get_anthropic()
    messages = list(history)

    # Tracks every tool name executed neste turno — usado pelo guardrail
    tools_called_this_turn: set[str] = set()
    # Quantas vezes o guardrail reinjetou lembrete (evita loop infinito)
    guardrail_retries = 0
    MAX_GUARDRAIL_RETRIES = 2
    # Quando True, força tool_choice=any no próximo round para quebrar
    # alucinações em que Claude insiste em emitir texto sem chamar ferramentas
    force_tool_use_next_round = False

    # Agentic loop — keep going until we get a stop_turn with no tool calls
    for _turn in range(10):  # max 10 tool rounds
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
                "tools": TOOL_SCHEMAS,
                "messages": messages,
            }
            if force_tool_use_next_round:
                create_kwargs["tool_choice"] = {"type": "any"}
                force_tool_use_next_round = False
            response = await client.messages.create(**create_kwargs)
        except RateLimitError:
            log.warning("anthropic.rate_limit")
            return "Estou sobrecarregado no momento, tente em alguns minutos. 🔄"
        except APIStatusError as exc:
            log.error("anthropic.api_error", status=exc.status_code)
            if exc.status_code == 402:
                await _alert_owner(
                    telegram_id,
                    "⚠️ *Alerta Alfred*: Créditos da Anthropic esgotados. O assistente está fora do ar até você recarregar em https://console.anthropic.com.",
                )
                return "Meus créditos acabaram. Já te avisei por aqui — recarrega lá no console da Anthropic para eu voltar. 💳"
            return "Ocorreu um erro no servidor, tente novamente. 🛠️"
        except APIConnectionError:
            log.error("anthropic.connection_error")
            return "Não consegui conectar ao servidor, tente novamente. 🔌"

        log.info(
            "agent.response",
            stop_reason=response.stop_reason,
            usage=response.usage.model_dump(),
        )

        # Collect tool calls from this response
        tool_calls = [b for b in response.content if isinstance(b, ToolUseBlock)]
        text_blocks = [b for b in response.content if isinstance(b, TextBlock)]

        if response.stop_reason == "end_turn" or not tool_calls:
            # ───── Guardrail: verifica ferramentas pendentes ─────
            missing = _detect_pending_actions(message, tools_called_this_turn)
            if missing and guardrail_retries < MAX_GUARDRAIL_RETRIES:
                guardrail_retries += 1
                log.warning(
                    "guardrail.pending_actions",
                    missing=missing,
                    tools_called=list(tools_called_this_turn),
                    retry=guardrail_retries,
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
                # Continua o diálogo: injeta a resposta de Claude + correção sintética como user
                messages.append({"role": "assistant", "content": response.content})  # type: ignore[typeddict-item]
                messages.append({"role": "user", "content": reminder_text})
                # Força Claude a chamar uma ferramenta no próximo round —
                # não pode mais escapar emitindo só texto
                force_tool_use_next_round = True
                continue

            # Guardrail esgotou retries mas ainda detecta ferramenta faltando →
            # NUNCA retornar texto alucinado. Responde erro explícito.
            if missing:
                log.error(
                    "guardrail.exhausted",
                    missing=missing,
                    tools_called=list(tools_called_this_turn),
                )
                error_msg = (
                    "Ops, algo travou aqui e eu não consegui executar tudo o que você pediu. "
                    "Pode repetir a mensagem? 🙏"
                )
                await _save_message(user_id, "assistant", error_msg)
                return error_msg

            # Final answer
            final_text = "\n".join(b.text for b in text_blocks).strip()
            if not final_text:
                final_text = "Feito."

            # Save assistant message
            await _save_message(user_id, "assistant", final_text)
            return final_text

        # Execute tool calls
        tool_results: list[ToolResultBlockParam] = []
        for tool_call in tool_calls:
            tools_called_this_turn.add(tool_call.name)
            try:
                result = await dispatch_tool(
                    tool_name=tool_call.name,
                    tool_input=dict(tool_call.input),  # type: ignore[arg-type]
                    user_id=user_id,
                )
            except Exception as exc:
                log.exception("tool.error", tool=tool_call.name)
                result = f"Erro ao executar ferramenta: {exc}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": result,
            })

        # Add assistant turn + tool results to messages
        messages.append({"role": "assistant", "content": response.content})  # type: ignore[typeddict-item]
        messages.append({"role": "user", "content": tool_results})  # type: ignore[typeddict-item]

    return "Não consegui completar a solicitação. Por favor, tente novamente."
