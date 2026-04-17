from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    AI_PROVIDER: str = "deepseek"

    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openai/gpt-4o-mini"

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-chat"

    PORT: int = 8000
    DATA_PATH: str = "./data"
    
    AUTH_ENABLED: bool = False
    AUTH_USERNAME: str = "admin"
    AUTH_PASSWORD: str = ""
    
    CORS_ALLOW_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:8002,http://127.0.0.1:8002"
    MAX_REQUEST_TIMEOUT: int = 60

    @property
    def data_path(self) -> Path:
        return Path(self.DATA_PATH)

    @property
    def db_path(self) -> Path:
        return self.data_path / "chat.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
