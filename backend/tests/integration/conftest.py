from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.db import (
    alembic_config,
    drop_database,
    recreate_database,
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
