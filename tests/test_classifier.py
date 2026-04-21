"""Tests for intent classifier."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alfred.agent.classifier import IntentResult, classify_intent


def _mock_response(intent: str, confidence: float = 0.95):
    """Create a mock Anthropic response with JSON content."""
    text_block = MagicMock()
    text_block.text = json.dumps({"intent": intent, "confidence": confidence})
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 20
    usage.cache_read_input_tokens = 0
    usage.cache_creation_input_tokens = 0
    response = MagicMock()
    response.content = [text_block]
    response.usage = usage
    return response


class TestClassifyIntent:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("me mostra os follow-ups da próxima semana", "QUERY"),
            ("quem eu conheço no Agibank?", "QUERY"),
            ("o que eu sei sobre a Maria?", "QUERY"),
            ("lista meus contatos", "QUERY"),
            ("falei com o João hoje", "ACTION"),
            ("cadastra o Pedro, ele é do BTG", "ACTION"),
            ("marca follow-up pra quinta", "ACTION"),
            ("O Thiago é de Java, a Stephanie reporta pra ele, o Emerson cuida de IA", "MULTI_ACTION"),
            ("oi Alfred", "CONVERSATION"),
            ("obrigado!", "CONVERSATION"),
            ("o que você consegue fazer?", "CONVERSATION"),
        ],
        ids=[
            "query-followups",
            "query-empresa",
            "query-memoria",
            "query-lista",
            "action-interacao",
            "action-cadastro",
            "action-followup",
            "multi-action",
            "conversation-oi",
            "conversation-obrigado",
            "conversation-capacidades",
        ],
    )
    async def test_classification(self, msg, expected):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_response(expected))

        with patch("alfred.agent.classifier.get_anthropic", return_value=mock_client), \
             patch("alfred.agent.classifier.record_usage", new_callable=AsyncMock):
            result = await classify_intent(msg)
            assert result.intent == expected
            assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_fallback_on_error(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))

        with patch("alfred.agent.classifier.get_anthropic", return_value=mock_client):
            result = await classify_intent("qualquer coisa")
            assert result.intent == "ACTION"
            assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self):
        text_block = MagicMock()
        text_block.text = "not json at all"
        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 20
        usage.cache_read_input_tokens = 0
        usage.cache_creation_input_tokens = 0
        response = MagicMock()
        response.content = [text_block]
        response.usage = usage

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        with patch("alfred.agent.classifier.get_anthropic", return_value=mock_client), \
             patch("alfred.agent.classifier.record_usage", new_callable=AsyncMock):
            result = await classify_intent("teste")
            assert result.intent == "ACTION"

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_intent(self):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response("UNKNOWN_INTENT")
        )

        with patch("alfred.agent.classifier.get_anthropic", return_value=mock_client), \
             patch("alfred.agent.classifier.record_usage", new_callable=AsyncMock):
            result = await classify_intent("teste")
            assert result.intent == "ACTION"

    def test_intent_result_frozen(self):
        r = IntentResult(intent="QUERY", confidence=0.9)
        with pytest.raises(AttributeError):
            r.intent = "ACTION"
