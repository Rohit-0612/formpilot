import io
import json
import logging

from fastapi.testclient import TestClient

from app.api import API_PREFIX
from app.api.deps import get_health_service
from app.config import Settings
from app.logging import configure_logging, get_logger
from app.main import create_app
from app.services.health import HealthReport, HealthService


def _lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_structlog_output_is_json_with_expected_keys() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    get_logger("formpilot.test").info("thing_happened", document_id="doc-1")

    (entry,) = _lines(stream)
    assert entry["event"] == "thing_happened"
    assert entry["level"] == "info"
    assert entry["logger"] == "formpilot.test"
    assert entry["document_id"] == "doc-1"
    assert "timestamp" in entry


def test_stdlib_loggers_are_rendered_as_json_too() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    logging.getLogger("uvicorn.error").info("server started")

    (entry,) = _lines(stream)
    assert entry["event"] == "server started"
    assert entry["logger"] == "uvicorn.error"


def test_level_filters_debug() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    get_logger("formpilot.test").debug("noisy")

    assert _lines(stream) == []


class _OkHealth(HealthService):
    def __init__(self) -> None:
        pass

    async def check(self) -> HealthReport:
        return HealthReport(db="ok", redis="ok")


def test_request_log_has_route_template_and_no_query_string(settings: Settings) -> None:
    app = create_app(settings)
    app.dependency_overrides[get_health_service] = _OkHealth
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)  # re-point output at our buffer

    with TestClient(app) as client:
        client.get("/api/v1/health?email=someone%40example.com", headers={"X-Request-ID": "req-1"})
        client.get("/api/v1/does-not-exist/private-value")

    output = stream.getvalue()
    requests = [entry for entry in _lines(stream) if entry["event"] == "request"]
    assert requests[0] == {
        **requests[0],
        "method": "GET",
        "route": "/api/v1/health",
        "status": 200,
        "request_id": "req-1",
    }
    assert isinstance(requests[0]["duration_ms"], float)
    assert requests[1]["route"] == "unmatched"
    assert requests[1]["status"] == 404
    assert "someone" not in output
    assert "private-value" not in output


def test_http_client_libraries_do_not_log_urls_at_info() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    logging.getLogger("httpx").info("HTTP Request: GET https://api.example/x?token=abc")
    logging.getLogger("httpcore").info("send_request_headers.started")

    assert _lines(stream) == []


def test_request_log_route_includes_api_prefix(settings: Settings) -> None:
    """Guards the router-level prefix workaround (docs/decisions/phase-1.md).

    FastAPI 0.141 stopped baking include_router(prefix=...) into route.path, which made the
    request log show "/health". If a FastAPI upgrade changes prefix handling again, this fails.
    """
    app = create_app(settings)
    app.dependency_overrides[get_health_service] = _OkHealth
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    with TestClient(app) as client:
        client.get("/api/v1/health")

    (request_log,) = [entry for entry in _lines(stream) if entry["event"] == "request"]
    assert request_log["route"] == "/api/v1/health"


def test_every_api_route_template_carries_the_prefix(settings: Settings) -> None:
    """A router added without prefix=API_PREFIX would serve and log the wrong path."""
    app = create_app(settings)
    framework_paths = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}

    api_paths = [path for path in app.openapi()["paths"] if path not in framework_paths]

    assert api_paths
    assert all(path.startswith(API_PREFIX + "/") for path in api_paths), api_paths


# --- exception messages are never logged -----------------------------------------

LEAKY_EMAIL = "asha.verma@example.com"


def _raise_leaky() -> None:
    raise ValueError(f"Key (email)=({LEAKY_EMAIL}) already exists")


def test_log_exception_keeps_type_and_stack_but_drops_the_message() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    try:
        _raise_leaky()
    except ValueError:
        get_logger("formpilot.test").exception("something_failed", document_id="doc-1")

    output = stream.getvalue()
    # The stack shows source lines (code such as the f-string template), never runtime values.
    assert LEAKY_EMAIL not in output
    assert f"Key (email)=({LEAKY_EMAIL}) already exists" not in output
    (entry,) = _lines(stream)
    assert entry["event"] == "something_failed"
    assert entry["level"] == "error"
    assert entry["exc_type"] == "ValueError"
    assert "_raise_leaky" in entry["stack"]
    assert "test_logging.py" in entry["stack"]
    assert "exc_info" not in entry
    assert "exception" not in entry


def test_stdlib_logger_exceptions_are_sanitised_too() -> None:
    """Third-party code (uvicorn, SQLAlchemy, arq) logs through the stdlib."""
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    try:
        _raise_leaky()
    except ValueError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")

    (entry,) = _lines(stream)
    assert LEAKY_EMAIL not in stream.getvalue()
    assert entry["exc_type"] == "ValueError"
    assert "_raise_leaky" in entry["stack"]


def test_exception_passed_as_exc_info_is_sanitised() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    try:
        _raise_leaky()
    except ValueError as exc:
        caught = exc
    get_logger("formpilot.test").error("stored_error", exc_info=caught)

    (entry,) = _lines(stream)
    assert LEAKY_EMAIL not in stream.getvalue()
    assert entry["exc_type"] == "ValueError"


def test_chained_exception_messages_are_dropped_and_types_kept() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    try:
        try:
            _raise_leaky()
        except ValueError as inner:
            raise RuntimeError(f"could not save {LEAKY_EMAIL}") from inner
    except RuntimeError:
        get_logger("formpilot.test").exception("save_failed")

    (entry,) = _lines(stream)
    assert LEAKY_EMAIL not in stream.getvalue()
    assert entry["exc_type"] == "RuntimeError"
    assert entry["exc_chain"] == ["RuntimeError", "ValueError"]


def test_console_renderer_drops_the_message_too() -> None:
    """LOG_JSON=false (local development) must be just as safe."""
    stream = io.StringIO()
    configure_logging("INFO", json=False, stream=stream)

    try:
        _raise_leaky()
    except ValueError:
        get_logger("formpilot.test").exception("something_failed")

    output = stream.getvalue()
    assert "something_failed" in output
    assert "ValueError" in output
    assert LEAKY_EMAIL not in output
