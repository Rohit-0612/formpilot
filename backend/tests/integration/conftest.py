from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import pytest
from alembic import command
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_queue
from app.config import Settings
from app.main import create_app
from tests.integration.db import (
    alembic_config,
    drop_database,
    recreate_database,
    redis_test_url,
    savepoint_session,
    truncate_all_tables,
)

TEST_DB_NAME = "formpilot_test"
PASSWORD = "correct-horse-7"


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


ClientFactory = Callable[..., Awaitable[AsyncClient]]


@pytest.fixture
async def client_for(live_settings: Settings) -> AsyncIterator[ClientFactory]:
    """Logged-in clients on one app (lifespan running), one per user; settings overridable."""
    stack: list[Any] = []

    async def make(
        email: str = "asha@example.com", settings: Settings | None = None, **overrides: Any
    ) -> AsyncClient:
        app = create_app(settings or live_settings)
        for dependency, override in overrides.items():
            app.dependency_overrides[{"get_queue": get_queue}[dependency]] = override
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        stack.append((client, lifespan))
        credentials = {"email": email, "password": PASSWORD}
        await client.post("/api/v1/auth/register", json=credentials)
        assert (await client.post("/api/v1/auth/login", json=credentials)).status_code == 200
        return client

    yield make
    for client, lifespan in reversed(stack):
        await client.aclose()
        await lifespan.__aexit__(None, None, None)
