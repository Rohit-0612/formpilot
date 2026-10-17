"""FastAPI dependencies. Resources live on app.state and are created in the app lifespan."""

import asyncio
from functools import partial
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyCookie
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User
from app.db.session import get_session
from app.logging import get_logger
from app.security import InvalidTokenError, decode_access_token
from app.services.documents import DocumentService
from app.services.health import HealthService, ping_database, ping_redis
from app.services.jobs import JobQueue, create_queue
from app.services.users import UserService
from app.storage.base import Storage

SESSION_COOKIE = "fp_session"

# Declares cookie auth in the OpenAPI schema; auto_error=False so we control the 401.
_session_cookie = APIKeyCookie(name=SESSION_COOKIE, auto_error=False)


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


log = get_logger(__name__)


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


async def get_queue(request: Request) -> JobQueue:
    """The arq pool, connected on first use rather than at startup: arq pings Redis (with
    retries) when the pool is created, which would make the API fail to start without Redis.
    """
    state = request.app.state
    if state.queue is None:
        async with state.queue_lock:
            if state.queue is None:
                try:
                    state.queue = await create_queue(state.settings)
                except Exception:
                    log.exception("job_queue_unavailable")
                    raise HTTPException(
                        status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job queue unavailable"
                    ) from None
    return state.queue


def new_queue_state() -> tuple[None, asyncio.Lock]:
    return None, asyncio.Lock()


def get_health_service(request: Request) -> HealthService:
    state = request.app.state
    return HealthService(
        db_probe=partial(ping_database, state.engine),
        redis_probe=partial(ping_redis, state.redis),
        timeout_seconds=state.settings.health_timeout_seconds,
    )


def get_user_service(session: Annotated[AsyncSession, Depends(get_session)]) -> UserService:
    return UserService(session)


def get_document_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> DocumentService:
    return DocumentService(session, storage, settings.file_ttl_hours)


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
