from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

VALID_SECRET = "a" * 64


@pytest.fixture
def base_env(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    clean_env.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    clean_env.setenv("REDIS_URL", "redis://redis:6379/0")
    clean_env.setenv("STORAGE_ROOT", "/data/storage")
    clean_env.setenv("JWT_SECRET", VALID_SECRET)
    return clean_env


def test_loads_from_environment(base_env: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"
    assert settings.storage_root == Path("/data/storage")
    assert settings.jwt_secret.get_secret_value() == VALID_SECRET
    assert settings.file_ttl_hours == 24
    assert settings.jwt_ttl_minutes == 60


def test_env_overrides_defaults(base_env: pytest.MonkeyPatch) -> None:
    base_env.setenv("JWT_TTL_MINUTES", "15")
    base_env.setenv("COOKIE_SECURE", "true")
    base_env.setenv("LOG_JSON", "false")

    settings = Settings(_env_file=None)

    assert settings.jwt_ttl_minutes == 15
    assert settings.cookie_secure is True
    assert settings.log_json is False


def test_cors_origins_are_comma_separated(base_env: pytest.MonkeyPatch) -> None:
    base_env.setenv("CORS_ORIGINS", "http://localhost:3000, https://formpilot.example ,")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["http://localhost:3000", "https://formpilot.example"]


def test_missing_jwt_secret_fails(base_env: pytest.MonkeyPatch) -> None:
    base_env.delenv("JWT_SECRET")

    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(_env_file=None)


@pytest.mark.parametrize("placeholder", ["", "change-me", "secret", "x" * 31])
def test_empty_or_placeholder_jwt_secret_fails(
    base_env: pytest.MonkeyPatch, placeholder: str
) -> None:
    base_env.setenv("JWT_SECRET", placeholder)

    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(_env_file=None)


def test_secret_is_not_exposed_in_repr(base_env: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None)

    assert VALID_SECRET not in repr(settings)


def test_missing_database_url_fails(base_env: pytest.MonkeyPatch) -> None:
    base_env.delenv("DATABASE_URL")

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_invalid_log_level_fails(base_env: pytest.MonkeyPatch) -> None:
    base_env.setenv("LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError, match="log_level"):
        Settings(_env_file=None)
