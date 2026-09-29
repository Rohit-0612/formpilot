"""FastAPI dependencies. Resources live on app.state and are created in the app lifespan."""

from functools import partial

from fastapi import Request

from app.config import Settings
from app.services.health import HealthService, ping_database, ping_redis


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_health_service(request: Request) -> HealthService:
    state = request.app.state
    return HealthService(
        db_probe=partial(ping_database, state.engine),
        redis_probe=partial(ping_redis, state.redis),
        timeout_seconds=state.settings.health_timeout_seconds,
    )
