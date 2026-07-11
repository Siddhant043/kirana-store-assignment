"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    anthropic_api_key: str
    database_url: str = "postgresql+asyncpg://kirana:kirana@localhost:5432/kirana"
    claude_model_id: str = "claude-sonnet-4-5"


def load_settings() -> Settings:
    # pydantic-settings populates required fields from the environment.
    return Settings()  # type: ignore[call-arg]
