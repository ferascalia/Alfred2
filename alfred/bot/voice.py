"""Voice transcription via Groq Whisper."""
import io

import httpx
import structlog

from alfred.config import settings

log = structlog.get_logger()


async def transcribe_voice(file_id: str) -> str:
    """Download a Telegram voice/audio file and transcribe via Groq Whisper."""
    # Get file path from Telegram
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
            params={"file_id": file_id},
        )
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]

        # Download the file
        audio_resp = await client.get(
            f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}",
        )
        audio_resp.raise_for_status()
        audio_bytes = audio_resp.content

    # Transcribe via Groq Whisper
    from groq import AsyncGroq
    groq = AsyncGroq(api_key=settings.groq_api_key)

    # Groq expects a file-like object with a name
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "audio.ogg"

    transcription = await groq.audio.transcriptions.create(
        file=audio_file,
        model="whisper-large-v3-turbo",
        language="pt",
        response_format="text",
    )

    log.info("voice.transcribed", file_id=file_id, length=len(str(transcription)))
    return str(transcription).strip()
