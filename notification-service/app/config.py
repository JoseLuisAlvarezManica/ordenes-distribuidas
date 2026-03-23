from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_notifications_url: str = os.getenv("POSTGRES_NOTIFICATIONS_URL", "")
    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_poll_seconds: float = float(os.getenv("TELEGRAM_POLL_SECONDS", "2"))
    telegram_poll_timeout: int = int(os.getenv("TELEGRAM_POLL_TIMEOUT", "30"))
    telegram_connect_timeout: float = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "10"))
    telegram_read_timeout: float = float(os.getenv("TELEGRAM_READ_TIMEOUT", "45"))
    telegram_retry_backoff_max: float = float(os.getenv("TELEGRAM_RETRY_BACKOFF_MAX", "30"))
    support_number: str | None = os.getenv("SUPPORT_NUMBER")


settings = Settings()