import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "")
    database_url: str = os.getenv("DATABASE_URL", "")


settings = Settings()
