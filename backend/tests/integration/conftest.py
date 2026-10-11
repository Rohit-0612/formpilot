from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from redis.asyncio import Redis
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from tests.integration.db import (
    alembic_config,
    drop_database,
    recreate_database,
    redis_test_url,
    savepoint_session,
    truncate_all_tables,
)

TEST_DB_NAME = "formpilot_test"


@pytest.fixture(scope="session")
def migrated_db_url() -> Iterator[URL]:
    """A fresh formpilot_test database at Alembic head, shared by the whole test session."""
    url = recreate_database(TEST_DB_NAME)
    command.upgrade(alembic_config(url), "head")
    yield url
    drop_database(TEST_DB_NAME)


@pytest.fixture
async def engine(migrated_db_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Rolled back after each test, even if the code under test calls commit() [A1]."""
    async with savepoint_session(engine) as session:
        yield session


@pytest.fixture
async def truncate_all(engine: AsyncEngine) -> AsyncIterator[None]:
    """Use in tests whose code commits through its own engine; empties every table afterwards."""
    yield
    await truncate_all_tables(engine)


@pytest.fixture
async def redis_url() -> AsyncIterator[str]:
    """A dedicated Redis database, flushed before and after the test."""
    url = redis_test_url()
    client = Redis.from_url(url)
    await client.flushdb()
    yield url
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def live_settings(settings: Settings, migrated_db_url: URL, redis_url: str) -> Settings:
    """Settings pointing at the test database and test Redis (for worker/CLI tests)."""
    return settings.model_copy(
        update={
            "database_url": migrated_db_url.render_as_string(hide_password=False),
            "redis_url": redis_url,
        }
    )
