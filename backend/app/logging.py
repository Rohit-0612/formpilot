"""Structured logging.

All output (ours, uvicorn's, SQLAlchemy's) goes through one stdlib handler rendered by structlog,
as JSON by default. Log ids, names, timings and statuses; never field values, emails or passwords.

Exceptions are logged as type + stack frames only (see drop_exception_messages), so
log.exception() is safe anywhere: exception messages often embed values.
"""

import logging
import sys
import traceback
from types import TracebackType
from typing import Any, TextIO

import structlog

_SHARED_PROCESSORS: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
]

_URL_LOGGING_LIBRARIES = ("httpx", "httpcore")

_ExcInfo = tuple[type[BaseException], BaseException, TracebackType | None]


def _resolve_exc_info(value: Any) -> _ExcInfo | None:
    if isinstance(value, BaseException):
        return type(value), value, value.__traceback__
    if isinstance(value, tuple) and len(value) == 3 and value[0] is not None:
        return value  # type: ignore[return-value]
    if value is True:
        current = sys.exc_info()
        return current if current[0] is not None else None  # type: ignore[return-value]
    return None


def _chain(exc: BaseException) -> list[str]:
    """Types of the exception and everything it was raised from / during, outermost first."""
    names: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.append(type(current).__qualname__)
        current = current.__cause__ or current.__context__
    return names


def drop_exception_messages(
    _logger: Any, _method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Replace exc_info with the exception type, its chain and the stack frames, no messages.

    Exception messages routinely embed values (e.g. psycopg's "Key (email)=(...) already
    exists"). Stack frames only show file, line, function and source code.
    """
    resolved = _resolve_exc_info(event_dict.pop("exc_info", None))
    if resolved is None:
        return event_dict
    exc_type, exc, tb = resolved
    event_dict["exc_type"] = exc_type.__qualname__
    chain = _chain(exc)
    if len(chain) > 1:
        event_dict["exc_chain"] = chain
    event_dict["stack"] = "".join(traceback.format_tb(tb))
    return event_dict


def configure_logging(level: str = "INFO", json: bool = True, stream: TextIO | None = None) -> None:
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*_SHARED_PROCESSORS, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # Caching would stop structlog.testing.capture_logs from seeing already-used loggers.
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_SHARED_PROCESSORS,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                drop_exception_messages,  # instead of format_exc_info, which renders messages
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Route uvicorn through our handler. Its access log is replaced by the request middleware.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False

    # HTTP client libraries log full URLs (including query strings) at INFO.
    for name in _URL_LOGGING_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)
