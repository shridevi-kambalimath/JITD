"""Configuration management.

All settings come from environment variables prefixed with MEDUSA_, optionally loaded from a
.env file in the project root. Relative paths are resolved against the project root, so the
backend behaves the same whichever directory it is started from.

No secrets are required by the current build. If one is added later (for example an LLM API key),
declare it here as SecretStr with no default, so it is never hardcoded and never logged.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/medusa/core/config.py -> project root is three levels above "medusa"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEDUSA_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # the shared .env also holds frontend-only keys
    )

    app_name: str = "MEDUSA-X"
    environment: Literal["development", "test", "production"] = "development"

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    reload: bool = False

    db_path: Path = Path("data/medusa.db")

    # Document ingestion
    upload_dir: Path = Path("data/uploads")          # original files, stored under generated names
    demo_dir: Path = Path("data/demo")               # fixed synthetic bundles, one folder per patient
    max_upload_bytes: int = Field(default=5_000_000, ge=1_000, le=50_000_000)
    max_pdf_pages: int = Field(default=50, ge=1, le=1_000)
    min_text_chars: int = Field(default=20, ge=1)     # extracted text shorter than this is rejected

    # Optional LLM extraction (Phase 3). Rules always run; the LLM only adds quote-verified claims.
    llm_provider: Literal["none", "anthropic", "openai_compatible"] = "none"
    llm_model: str = ""
    llm_api_key: SecretStr | None = None   # never logged, never returned by the API
    llm_base_url: str = ""                 # empty = the provider's public endpoint
    llm_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=5)

    # Single-process demo (Phase 11): the backend also serves the built UI from frontend_dist on the same port.
    serve_frontend: bool = False
    frontend_dist: Path = Path("frontend/dist")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["text", "json"] = "text"
    log_file: Path | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper() if isinstance(v, str) else v

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def _empty_key_is_none(cls, v):
        return None if v in ("", None) else v

    @field_validator("log_file", mode="before")
    @classmethod
    def _empty_is_none(cls, v):
        return None if v in ("", None) else v

    @field_validator("db_path", "log_file", "upload_dir", "demo_dir", "frontend_dist")
    @classmethod
    def _resolve(cls, v: Path | None) -> Path | None:
        if v is None:
            return None
        return v if v.is_absolute() else (PROJECT_ROOT / v).resolve()

    @property
    def docs_enabled(self) -> bool:
        """Interactive API docs are disabled in production."""
        return self.environment != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
