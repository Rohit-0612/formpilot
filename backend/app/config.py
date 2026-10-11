"""Application configuration, loaded only from environment variables (and an optional .env)."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The repository root holds the single .env used by compose and by host-side tools.
# Inside the container this path does not exist and only real env vars are used.
_REPO_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

JWT_SECRET_MIN_LENGTH = 32


_SETTINGS_CONFIG = SettingsConfigDict(
    env_file=_REPO_ENV_FILE,
    env_file_encoding="utf-8",
    extra="ignore",
)


class DatabaseSettings(BaseSettings):
    """Only what Alembic and database tooling need, so they do not require JWT_SECRET etc."""

    model_config = _SETTINGS_CONFIG

    database_url: str


class QueueSettings(BaseSettings):
    """Only what Redis tooling needs (e.g. the test suite's queue fixtures)."""

    model_config = _SETTINGS_CONFIG

    redis_url: str


class Settings(DatabaseSettings, QueueSettings):
    model_config = _SETTINGS_CONFIG

    # database_url and redis_url are inherited.

    # Auth
    jwt_secret: SecretStr
    jwt_ttl_minutes: int = Field(default=60, gt=0)
    cookie_secure: bool = False
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Storage and retention
    storage_root: Path
    file_ttl_hours: int = Field(default=24, gt=0)

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    # Health checks
    health_timeout_seconds: float = Field(default=2.0, gt=0)

    # Background jobs
    job_timeout_seconds: int = Field(default=300, gt=0)

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_strong_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < JWT_SECRET_MIN_LENGTH:
            raise ValueError(
                f"JWT_SECRET must be at least {JWT_SECRET_MIN_LENGTH} characters; "
                "generate one with `openssl rand -hex 32`"
            )
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
