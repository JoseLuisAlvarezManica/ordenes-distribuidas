from pydantic import field_validator, AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_url: str = Field(validation_alias=AliasChoices("POSTGRES_AUTH_URL", "database_url"))
    encryption_key: str = Field(validation_alias=AliasChoices("PRIVATE_KEY", "encryption_key"))
    public_key: str = Field(validation_alias=AliasChoices("PUBLIC_KEY", "public_key"))
    redis_url: str = Field(default="redis://redis:6379/0", validation_alias=AliasChoices("REDIS_URL", "redis_url"))
    access_token_expire_minutes: int = Field(default=30, validation_alias=AliasChoices("ACCESS_TOKEN_EXPIRE_MINUTES", "access_token_expire_minutes"))
    redis_user: str = Field(default="", validation_alias=AliasChoices("REDIS_USER", "redis_user"))
    redis_password: str = Field(default="", validation_alias=AliasChoices("REDIS_PASSWORD", "redis_password"))

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        if v and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v and v.startswith("postgresql+psycopg2://"):
            return v.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        return v



settings = Settings()
