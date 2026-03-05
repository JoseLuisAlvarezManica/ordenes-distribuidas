from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    
    database_url: str = os.getenv("DATABASE_URL")

    redis_url: str = os.getenv("REDIS_URL")


settings = Settings()
