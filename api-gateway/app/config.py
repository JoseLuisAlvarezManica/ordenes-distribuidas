from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = os.getenv("REDIS_URL")

    auth_service_url: str = os.getenv("AUTH_SERVICE_URL")

    writer_service_url: str = os.getenv("WRITER_SERVICE_URL")
    writer_timeout_seconds: float = os.getenv("WRITER_TIMEOUT_SECONDS")
    writer_max_retries: int = os.getenv("WRITER_MAX_RETRIES")
    support_number: str | None = os.getenv("SUPPORT_NUMBER")


settings = Settings()
