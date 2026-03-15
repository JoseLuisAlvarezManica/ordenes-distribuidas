from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = os.getenv("DATABASE_URL", "")
    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_poll_seconds: float = float(os.getenv("TELEGRAM_POLL_SECONDS", "2"))
    support_number: str | None = os.getenv("SUPPORT_NUMBER")


settings = Settings()
