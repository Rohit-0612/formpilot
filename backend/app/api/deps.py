"""FastAPI dependencies. Resources live on app.state and are created in the app lifespan."""

from functools import partial
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyCookie
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User
from app.db.session import get_session
from app.security import InvalidTokenError, decode_access_token
from app.services.health import HealthService, ping_database, ping_redis
from app.services.users import UserService

SESSION_COOKIE = "fp_session"

# Declares cookie auth in the OpenAPI schema; auto_error=False so we control the 401.
_session_cookie = APIKeyCookie(name=SESSION_COOKIE, auto_error=False)


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_health_service(request: Request) -> HealthService:
    state = request.app.state
    return HealthService(
        db_probe=partial(ping_database, state.engine),
        redis_probe=partial(ping_redis, state.redis),
        timeout_seconds=state.settings.health_timeout_seconds,
    )


def get_user_service(session: Annotated[AsyncSession, Depends(get_session)]) -> UserService:
    return UserService(session)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def get_current_user(
    token: Annotated[str | None, Depends(_session_cookie)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    users: Annotated[UserService, Depends(get_user_service)],
) -> User:
    if not token:
        raise _unauthorized()
    try:
        user_id = decode_access_token(token, settings.jwt_secret.get_secret_value())
    except InvalidTokenError:
        raise _unauthorized() from None
    user = await users.get(user_id)
    if user is None:
        raise _unauthorized()
    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
