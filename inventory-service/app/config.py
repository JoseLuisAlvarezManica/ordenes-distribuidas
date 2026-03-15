from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = os.getenv("DATABASE_URL")
    rabbitmq_url: str = os.getenv("RABBITMQ_URL")


settings = Settings()
