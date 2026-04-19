import anthropic

from alfred.config import settings

_client: anthropic.AsyncAnthropic | None = None


def get_anthropic() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            max_retries=3,
        )
    return _client


MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
