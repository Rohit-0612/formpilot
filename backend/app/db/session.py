"""Database engine construction. Session handling is added with the models (Phase 1, step 2)."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)
