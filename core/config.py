"""Application configuration loaded from environment variables."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory -- used to resolve relative paths (e.g. the Google
# service-account credentials file) regardless of the process's cwd.
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "sqlite:///./data/sync.db"

    # Google Sheets export (optional supplementary sink -- see
    # services/google_sheets.py). Leave GOOGLE_SPREADSHEET_ID unset to
    # disable; SQLite remains the source of truth either way.
    google_sheets_credentials_file: str | None = "credentials/google-service-account.json"
    google_spreadsheet_id: str | None = None

    @property
    def google_sheets_credentials_path(self) -> Path | None:
        if not self.google_sheets_credentials_file:
            return None
        path = Path(self.google_sheets_credentials_file)
        return path if path.is_absolute() else BASE_DIR / path

    # AI-assisted generic extraction (optional -- powers "request a new
    # manufacturer" -> AI preview/approve, for manufacturers with no
    # hand-written adapter). Uses a local Ollama server so there's no
    # per-request API cost; point OLLAMA_HOST elsewhere if Ollama runs on
    # another machine.
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"

    # API
    api_prefix: str = "/api"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Crawling defaults (per-manufacturer config can override)
    default_request_delay_seconds: float = 1.0
    default_timeout_seconds: float = 15.0
    default_max_retries: int = 3
    default_user_agent: str = (
        "DataCrawlerSyncBot/1.0 (+https://github.com/; contact: jace.tran@avs-tek.vn)"
    )

    # Logging
    log_level: str = "INFO"


settings = Settings()
