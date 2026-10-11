"""Liveness checks for the API's dependencies (Postgres and Redis)."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.logging import get_logger

log = get_logger(__name__)

ComponentStatus = Literal["ok", "error"]
Probe = Callable[[], Awaitable[object]]


@dataclass(frozen=True)
class HealthReport:
    db: ComponentStatus
    redis: ComponentStatus

    @property
    def ok(self) -> bool:
        return self.db == "ok" and self.redis == "ok"


async def ping_database(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def ping_redis(redis: Redis) -> None:
    await redis.ping()


class HealthService:
    def __init__(self, db_probe: Probe, redis_probe: Probe, timeout_seconds: float) -> None:
        self._db_probe = db_probe
        self._redis_probe = redis_probe
        self._timeout = timeout_seconds

    async def check(self) -> HealthReport:
        db, redis = await asyncio.gather(
            self._run("db", self._db_probe),
            self._run("redis", self._redis_probe),
        )
        return HealthReport(db=db, redis=redis)

    async def _run(self, component: str, probe: Probe) -> ComponentStatus:
        try:
            await asyncio.wait_for(probe(), timeout=self._timeout)
        except Exception as exc:
            # Only the exception class: messages can contain connection details.
            log.warning("health_probe_failed", component=component, error=type(exc).__name__)
            return "error"
        return "ok"
