"""FastAPI application factory. Run with: uvicorn app.main:create_app --factory"""

import re
import time
import traceback
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.api.errors import register_error_handlers
from app.api.router import api_router
from app.config import Settings, get_settings
from app.db.session import make_engine, make_sessionmaker
from app.logging import configure_logging, get_logger

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")

log = get_logger(__name__)


def _request_id(request: Request) -> str:
    incoming = request.headers.get(REQUEST_ID_HEADER)
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


def _route_template(request: Request) -> str:
    # Log the route template (e.g. /api/v1/documents/{id}), never the raw path or query string.
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = _request_id(request)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        # Log the exception type and stack frames only. Exception messages can carry values
        # (e.g. an IntegrityError's "Key (email)=(...)"), so they are never logged. Returning a
        # response here also stops uvicorn from logging the full exception itself.
        log.error(
            "request_failed",
            method=request.method,
            route=_route_template(request),
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
            exc_type=type(exc).__name__,
            stack="".join(traceback.format_tb(exc.__traceback__)),
        )
        response = JSONResponse(
            status_code=500, content={"detail": "Internal server error", "request_id": request_id}
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    log.info(
        "request",
        method=request.method,
        route=_route_template(request),
        status=response.status_code,
        duration_ms=round((time.perf_counter() - start) * 1000, 1),
    )
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Neither call connects yet; connections are opened lazily on first use.
        app.state.engine = make_engine(settings)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        app.state.redis = Redis.from_url(settings.redis_url)
        log.info("startup")
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.engine.dispose()
            log.info("shutdown")

    app = FastAPI(title="FormPilot API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    app.middleware("http")(log_requests)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    register_error_handlers(app)
    app.include_router(api_router)
    return app
