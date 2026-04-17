from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Telegram
    telegram_bot_token: str

    # Anthropic
    anthropic_api_key: str

    # Voyage AI
    voyage_api_key: str

    # Supabase
    supabase_url: str
    supabase_service_role_key: str

    # App
    webhook_url: str
    webhook_secret: str = ""
    log_level: str = "INFO"
    environment: str = "production"

    # Jobs
    jobs_secret: str = ""

    # Groq (Whisper)
    groq_api_key: str = ""

    # Railway
    railway_api_token: str = ""


settings = Settings()  # type: ignore[call-arg]
