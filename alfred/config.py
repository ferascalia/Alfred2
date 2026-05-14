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

    # Admin alerts (comma-separated Telegram IDs)
    admin_telegram_id: str = ""
    anthropic_monthly_budget_usd: float = 5.0

    @property
    def admin_telegram_ids(self) -> list[int]:
        if not self.admin_telegram_id:
            return []
        return [int(x.strip()) for x in self.admin_telegram_id.split(",") if x.strip()]

    # Multi-tenant access control
    allowed_telegram_ids: str = ""

    # Resend (email / calendar invites)
    resend_api_key: str = ""
    calendar_sender_email: str = ""

    # Google OAuth (Calendar integration)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""


settings = Settings()  # type: ignore[call-arg]
