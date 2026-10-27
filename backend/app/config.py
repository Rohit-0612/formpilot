"""Application configuration, loaded only from environment variables (and an optional .env)."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.vault.crypto import check_vault_key

# The repository root holds the single .env used by compose and by host-side tools.
# Inside the container this path does not exist and only real env vars are used.
_REPO_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

JWT_SECRET_MIN_LENGTH = 32


_SETTINGS_CONFIG = SettingsConfigDict(
    env_file=_REPO_ENV_FILE,
    env_file_encoding="utf-8",
    extra="ignore",
    # A rejected secret (JWT_SECRET, VAULT_KEY) must not be echoed in the startup error.
    hide_input_in_errors=True,
)


class DatabaseSettings(BaseSettings):
    """Only what Alembic and database tooling need, so they do not require JWT_SECRET etc."""

    model_config = _SETTINGS_CONFIG

    database_url: str


class QueueSettings(BaseSettings):
    """Only what Redis tooling needs (e.g. the test suite's queue fixtures)."""

    model_config = _SETTINGS_CONFIG

    redis_url: str


class GroqSettings(BaseSettings):
    """Only the Groq key, for host-side tools such as the understanding eval."""

    model_config = _SETTINGS_CONFIG

    # Optional, remote: sensitive and phone values are never sent (app/llm/provider.py)
    groq_api_key: SecretStr | None = None


class Settings(DatabaseSettings, QueueSettings, GroqSettings):
    model_config = _SETTINGS_CONFIG

    # database_url, redis_url and groq_api_key are inherited.

    # Auth
    jwt_secret: SecretStr
    jwt_ttl_minutes: int = Field(default=60, gt=0)
    # Fernet key for the profile vault and the sensitive values in stored IR versions (P4-D5)
    vault_key: SecretStr
    cookie_secure: bool = False
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Storage and retention
    storage_root: Path
    file_ttl_hours: int = Field(default=24, gt=0)

    # Uploads (SPEC §8, decision D3): size and magic bytes checked by the API, pages by the worker
    max_upload_mb: int = Field(default=20, gt=0)
    max_pages: int = Field(default=50, gt=0)
    page_image_dpi: int = Field(default=144, ge=36, le=600)

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    # Health checks
    health_timeout_seconds: float = Field(default=2.0, gt=0)

    # Background jobs
    job_timeout_seconds: int = Field(default=300, gt=0)

    # Field understanding: "auto" uses Groq when GROQ_API_KEY is set, with Ollama as the fallback,
    # else Ollama (decision P4-D1); "none" runs the rule matcher only
    llm_provider: Literal["auto", "none", "ollama", "groq"] = "auto"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = Field(default=300.0, gt=0)
    # Fields whose semantic confidence is below this get status NEEDS_REVIEW (SPEC §6.2)
    understand_review_threshold: float = Field(default=0.7, ge=0.0, le=1.0)

    # Fill policy (decision P4-D2, chosen on dev in the Phase 4 tuning session): an LLM-typed
    # field is filled from the profile only at this confidence; person and date types at most
    # once per form
    fill_min_confidence: float = Field(default=0.99, ge=0.0, le=1.0)
    fill_once_per_form: bool = True
    # Fit pass (SPEC §6.7), points
    fit_font_size: float = Field(default=10.0, gt=0)
    fit_min_font_size: float = Field(default=6.0, gt=0)

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_strong_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < JWT_SECRET_MIN_LENGTH:
            raise ValueError(
                f"JWT_SECRET must be at least {JWT_SECRET_MIN_LENGTH} characters; "
                "generate one with `openssl rand -hex 32`"
            )
        return value

    @field_validator("vault_key")
    @classmethod
    def _vault_key_is_a_fernet_key(cls, value: SecretStr) -> SecretStr:
        check_vault_key(value.get_secret_value())
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
