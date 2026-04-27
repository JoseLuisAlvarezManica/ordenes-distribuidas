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

    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "")
    telegram_bot_service_url: str = os.getenv(
        "TELEGRAM_BOT_SERVICE_URL", "http://telegram-bot:8003"
    )


settings = Settings()
