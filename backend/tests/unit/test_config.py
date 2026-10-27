from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import DatabaseSettings, Settings
from app.llm.factory import provider_from_settings
from app.llm.fallback import FallbackProvider
from app.llm.groq import GroqProvider
from app.llm.ollama import OllamaProvider
from tests.conftest import TEST_VAULT_KEY

VALID_SECRET = "a" * 64


@pytest.fixture
def base_env(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    clean_env.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    clean_env.setenv("REDIS_URL", "redis://redis:6379/0")
    clean_env.setenv("STORAGE_ROOT", "/data/storage")
    clean_env.setenv("JWT_SECRET", VALID_SECRET)
    clean_env.setenv("VAULT_KEY", TEST_VAULT_KEY)
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


def test_database_settings_need_only_database_url(clean_env: pytest.MonkeyPatch) -> None:
    """Alembic and DB tooling must not require JWT_SECRET, REDIS_URL, etc."""
    clean_env.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")

    assert DatabaseSettings(_env_file=None).database_url == "postgresql+psycopg://u:p@db:5432/x"


def test_groq_provider_takes_its_key_from_the_environment_and_hides_it(
    base_env: pytest.MonkeyPatch,
) -> None:
    base_env.setenv("LLM_PROVIDER", "groq")
    base_env.setenv("GROQ_MODEL", "openai/gpt-oss-20b")
    base_env.setenv("GROQ_API_KEY", "gsk_test_not_a_real_key")

    settings = Settings(_env_file=None)
    provider = provider_from_settings(settings)

    assert isinstance(provider, GroqProvider) and provider.is_remote
    assert provider.model == "openai/gpt-oss-20b"
    assert "gsk_test_not_a_real_key" not in repr(settings)


def test_groq_key_is_optional(base_env: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None).groq_api_key is None


@pytest.mark.parametrize("key", [None, ""])
def test_auto_without_a_groq_key_uses_local_ollama(
    base_env: pytest.MonkeyPatch, key: str | None
) -> None:
    if key is not None:
        base_env.setenv("GROQ_API_KEY", key)

    provider = provider_from_settings(Settings(_env_file=None))

    assert isinstance(provider, OllamaProvider) and not provider.is_remote
    assert provider.model == "qwen3:8b"


def test_auto_with_a_groq_key_uses_groq_then_ollama(base_env: pytest.MonkeyPatch) -> None:
    """Decision P4-D1: Groq gpt-oss-120b by default, local Ollama as the fallback."""
    base_env.setenv("GROQ_API_KEY", "gsk_test_not_a_real_key")

    provider = provider_from_settings(Settings(_env_file=None))

    assert isinstance(provider, FallbackProvider)
    assert isinstance(provider.primary, GroqProvider)
    assert provider.primary.model == "openai/gpt-oss-120b"
    assert isinstance(provider.fallback, OllamaProvider)


def test_provider_none_runs_rules_only(base_env: pytest.MonkeyPatch) -> None:
    base_env.setenv("LLM_PROVIDER", "none")
    base_env.setenv("GROQ_API_KEY", "gsk_test_not_a_real_key")

    assert provider_from_settings(Settings(_env_file=None)) is None


@pytest.mark.parametrize("key", ["", "not-a-fernet-key", "a" * 44])
def test_vault_key_must_be_a_fernet_key(base_env: pytest.MonkeyPatch, key: str) -> None:
    base_env.setenv("VAULT_KEY", key)

    with pytest.raises(ValidationError, match="VAULT_KEY must be a Fernet key") as error:
        Settings(_env_file=None)
    assert not key or key not in str(error.value)  # the rejected key is not echoed back


def test_missing_vault_key_fails(base_env: pytest.MonkeyPatch) -> None:
    base_env.delenv("VAULT_KEY")

    with pytest.raises(ValidationError, match="vault_key"):
        Settings(_env_file=None)
