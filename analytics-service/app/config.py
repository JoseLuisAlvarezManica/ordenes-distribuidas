import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "")
    database_url: str = os.getenv("DATABASE_URL", "")
    analytics_admin_token: str = os.getenv("ANALYTICS_ADMIN_TOKEN", "")


settings = Settings()
