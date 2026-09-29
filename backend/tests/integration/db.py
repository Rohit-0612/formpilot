"""Database helpers for integration tests (shared by conftest and the tests themselves)."""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import URL, create_engine, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.pool import NullPool

from app.config import DatabaseSettings, QueueSettings
from app.db.base import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]
_SAFE_DB_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def server_url() -> URL:
    """DATABASE_URL from the environment or the repo .env (see `make services`)."""
    try:
        return make_url(DatabaseSettings().database_url)  # type: ignore[call-arg]
    except ValidationError as exc:
        raise RuntimeError(
            "DATABASE_URL is not set. Run `make services` (creates .env and starts Postgres)."
        ) from exc


def _admin_execute(*statements: str) -> None:
    engine = create_engine(server_url(), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with engine.connect() as conn:
            for statement in statements:
                conn.execute(text(statement))
    finally:
        engine.dispose()


def recreate_database(name: str) -> URL:
    """Drop (if present) and create an empty database next to the configured one."""
    if not _SAFE_DB_NAME.fullmatch(name):
        raise ValueError(f"unsafe database name: {name!r}")
    _admin_execute(
        f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',
        f'CREATE DATABASE "{name}"',
    )
    return server_url().set(database=name)


def drop_database(name: str) -> None:
    if not _SAFE_DB_NAME.fullmatch(name):
        raise ValueError(f"unsafe database name: {name!r}")
    _admin_execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def alembic_config(url: URL) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # configparser treats % as interpolation, so escape it in the URL.
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    config.attributes["configure_logger"] = False
    return config


@asynccontextmanager
async def savepoint_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session whose commit() only releases a SAVEPOINT; everything is rolled back at the end.

    One connection, an outer transaction, and join_transaction_mode="create_savepoint": service
    code can call commit() as it does in production, and the test still leaves no rows behind.
    """
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


async def truncate_all_tables(engine: AsyncEngine) -> None:
    """For tests whose code uses its own engine/connection (e.g. the arq worker)."""
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


# --- Redis -----------------------------------------------------------------------

TEST_REDIS_DB = 15


def redis_test_url() -> str:
    """REDIS_URL with the database index replaced by TEST_REDIS_DB (never the dev queue)."""
    try:
        base = QueueSettings().redis_url  # type: ignore[call-arg]
    except ValidationError as exc:
        raise RuntimeError(
            "REDIS_URL is not set. Run `make services` (creates .env and starts Redis)."
        ) from exc
    parts = urlsplit(base)
    return urlunsplit(parts._replace(path=f"/{TEST_REDIS_DB}"))
