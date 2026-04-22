from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]


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
    APP_LOG_PATH: str = "./app.log"
    
    AUTH_ENABLED: bool = False
    AUTH_USERNAME: str = "admin"
    AUTH_PASSWORD: str = ""
    
    CORS_ALLOW_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:8002,http://127.0.0.1:8002"
    MAX_REQUEST_TIMEOUT: int = 60
    AI_TEMPERATURE: float = 0.7
    MAX_TOKENS: int = 2000
    CONTEXT_SIZE: str = "medium"
    CUSTOM_CONTEXT_SIZE: int = 20000
    ENABLE_STREAMING: bool = True
    AUTO_SAVE_ARTIFACTS: bool = False

    # Obsidian vault (VM-side path; optional WebDAV sync via docker-compose)
    OBSIDIAN_ENABLED: bool = False
    OBSIDIAN_VAULT_PATH: str = "./obsidian-vault"
    VAULT_AUTO_LOG_CHATS: bool = False
    VAULT_AI_FOLDER: str = "AI-Generated"
    VAULT_CHATS_FOLDER: str = "Chats"
    VAULT_ARTIFACT_AUTOSAVE_THRESHOLD: float = 0.67
    VAULT_AUTOSAVE_MODE: str = "structured"  # off | summary | structured
    VAULT_RETRIEVAL_MAX_FILES: int = 6
    VAULT_RETRIEVAL_MAX_SECTIONS: int = 12
    VAULT_RETRIEVAL_MAX_CHARS: int = 32000

    WEBDAV_PORT: int = 8081
    WEBDAV_USER: str = "obsidian"
    WEBDAV_PASSWORD: str = ""

    @property
    def data_path(self) -> Path:
        path = Path(self.DATA_PATH)
        return path if path.is_absolute() else (BASE_DIR / path).resolve()

    @property
    def db_path(self) -> Path:
        return self.data_path / "chat.db"

    @property
    def app_log_path(self) -> Path:
        path = Path(self.APP_LOG_PATH)
        return path if path.is_absolute() else (BASE_DIR / path).resolve()

    @property
    def obsidian_vault_path(self) -> Path:
        path = Path(self.OBSIDIAN_VAULT_PATH)
        return path.resolve() if path.is_absolute() else (BASE_DIR / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
