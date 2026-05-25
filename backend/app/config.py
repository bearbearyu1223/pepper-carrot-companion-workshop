"""Application settings loaded from environment variables.

All configuration in one place. Read this file before changing any of the
provider/storage selection logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor the .env lookup to the repo root so settings load identically whether
# the process starts from the repo root, backend/, ingestion/, or anywhere else.
# config.py lives at backend/app/config.py — parents[2] is the repo root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Top-level settings. Set values via environment variables or a .env file."""

    # `model_config` is a magic attribute name pydantic v2 (and pydantic-settings)
    # reads at class-definition time to configure how Settings() loads its values.
    # No application code references it — pydantic itself consumes it. Each
    # argument below configures one piece of load behavior:
    #
    # - env_file: anchored to repo root via _PROJECT_ROOT so the same Settings
    #     class loads identically whether the process starts from the repo root,
    #     backend/, ingestion/, or anywhere else. Without anchoring, the relative
    #     path would resolve against CWD, giving three different effective .env
    #     locations depending on where uvicorn / pytest / ingest.py was launched.
    # - env_file_encoding: defensive UTF-8 pin. Without it, the system locale
    #     decides — usually UTF-8 on macOS/Linux, Windows-1252 on Windows — and
    #     non-ASCII values in .env (e.g. an accented password) parse differently
    #     across developers' machines.
    # - case_sensitive=False: lets POSTGRES_USER (uppercase, Unix env-var
    #     convention) in .env map to the postgres_user field (lowercase, Python
    #     attribute convention). Without it, every .env line would have to be
    #     written lowercase, which looks wrong in a shell context.
    # - extra="ignore": tolerate keys that .env carries for other consumers —
    #     notably VITE_API_BASE_URL, which Vite reads but Python doesn't. Without
    #     this, the unknown key would raise ValidationError on construction and
    #     the backend wouldn't boot.
    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === Database ===
    postgres_user: str = "peppercarrot"
    postgres_password: str = "peppercarrot_dev"
    postgres_db: str = "peppercarrot"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Single-string override. Set this for managed Postgres providers
    # (e.g. Neon) that hand you one connection string. Format:
    #   postgresql+asyncpg://user:pass@host/db?ssl=true
    # When set, takes precedence over the component fields above.
    database_url_override: str | None = None

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # === ChromaDB ===
    # Anchored to the repo root, like .env, so the backend, the ingestion
    # script, and the frontend dev server all see the same store regardless of
    # which directory they were started from.
    chroma_persist_dir: Path = _PROJECT_ROOT / "data" / "chroma"

    # === Storage ===
    storage_backend: Literal["local", "r2"] = "local"
    local_image_dir: Path = _PROJECT_ROOT / "data" / "images"
    local_image_url_prefix: str = "http://localhost:8000/images"

    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    r2_public_url_prefix: str | None = None

    # === Model providers ===
    # Vision is always sourced from sibling JSON files written by the
    # `ingest-from-images` Claude Code skill — see JsonFileVisionClient.
    # The Literal is kept (rather than removed entirely) so the env var
    # documents the provider explicitly.
    vision_provider: Literal["json"] = "json"
    chat_provider: Literal["ollama", "anthropic"] = "ollama"
    embedding_provider: Literal["sentence-transformers", "ollama", "anthropic"] = (
        "sentence-transformers"
    )

    # Ollama (chat + embeddings)
    ollama_base_url: str = "http://localhost:11434"
    # Text-only model — chat uses retrieved descriptions, never an image.
    ollama_chat_model: str = "qwen2.5:7b"

    # Modal proxy auth — set when ollama_base_url points at a Modal endpoint
    # deployed with requires_proxy_auth=True. Generate from the Modal dashboard:
    # https://modal.com/settings → workspace → Proxy Auth Tokens → Create.
    # Both must be set together; either-or is a config error.
    modal_proxy_token_id: str | None = None
    modal_proxy_token_secret: str | None = None

    # Embeddings
    embedding_model: str = "BAAI/bge-m3"

    # Anthropic
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-7"

    # === Backend ===
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("chroma_persist_dir", "local_image_dir", mode="after")
    @classmethod
    def _anchor_to_project_root(cls, v: Path) -> Path:
        """Resolve relative paths against the repo root (not CWD).

        The .env conventionally writes these as `./data/images` etc. Without this,
        the value would resolve against whatever directory the process was started
        from — silently giving the backend, ingestion script, and tests three
        different effective locations.
        """
        return v if v.is_absolute() else (_PROJECT_ROOT / v).resolve()


_settings: Settings | None = None


def get_settings() -> Settings:
    """Singleton accessor. Use this everywhere instead of constructing Settings()."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
