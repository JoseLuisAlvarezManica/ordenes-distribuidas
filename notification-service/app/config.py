from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_notifications_url: str = os.getenv("POSTGRES_NOTIFICATIONS_URL", "")
    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "")
    telegram_bot_service_url: str = os.getenv(
        "TELEGRAM_BOT_SERVICE_URL", "http://telegram-bot:8003"
    )


settings = Settings()