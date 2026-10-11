from pathlib import Path

import pytest

from app.config import Settings

TESTS_DIR = Path(__file__).parent

# Obviously fake, but long enough to pass the JWT_SECRET length check.
TEST_JWT_SECRET = "test-secret-" + "x" * 40


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark tests by folder so `pytest -m unit` / `-m integration` select the right ones."""
    for item in items:
        path = Path(str(item.path))
        if (TESTS_DIR / "unit") in path.parents:
            item.add_marker(pytest.mark.unit)
        elif (TESTS_DIR / "integration") in path.parents:
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every Settings variable from the environment so tests only see what they set."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    return monkeypatch


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings for unit tests. The URLs point at nothing; unit tests never connect."""
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unit:unit@127.0.0.1:9/unit",
        redis_url="redis://127.0.0.1:9/0",
        jwt_secret=TEST_JWT_SECRET,
        storage_root=tmp_path / "storage",
        cors_origins=["http://localhost:3000"],
        log_json=True,
    )
