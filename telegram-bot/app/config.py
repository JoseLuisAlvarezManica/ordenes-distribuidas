import os
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_notifications_url: str = os.getenv("POSTGRES_NOTIFICATIONS_URL", "")

    @field_validator("postgres_notifications_url", mode="before")
    @classmethod
    def fix_postgres_notifications_url(cls, v: str) -> str:
        if v and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v and v.startswith("postgresql+psycopg2://"):
            return v.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        return v

    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_api_base_url: str = os.getenv("TELEGRAM_API_BASE_URL", "https://api.telegram.org")
    telegram_bot_host: str = os.getenv("TELEGRAM_BOT_HOST", "0.0.0.0")
    telegram_bot_port: int = int(os.getenv("TELEGRAM_BOT_PORT", "8003"))
    telegram_poll_seconds: float = float(os.getenv("TELEGRAM_POLL_SECONDS", "2"))
    telegram_poll_timeout: int = int(os.getenv("TELEGRAM_POLL_TIMEOUT", "30"))
    telegram_connect_timeout: float = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "10"))
    telegram_read_timeout: float = float(os.getenv("TELEGRAM_READ_TIMEOUT", "45"))
    telegram_retry_backoff_max: float = float(os.getenv("TELEGRAM_RETRY_BACKOFF_MAX", "30"))


settings = Settings()
