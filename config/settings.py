from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    AI_PROVIDER: str = "openrouter"

    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openai/gpt-4o-mini"

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-chat"

    PORT: int = 8000
    DATA_PATH: str = "./data"

    @property
    def data_path(self) -> Path:
        return Path(self.DATA_PATH)

    @property
    def db_path(self) -> Path:
        return self.data_path / "chat.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
