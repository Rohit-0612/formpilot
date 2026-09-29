import io
import json
import logging

from fastapi.testclient import TestClient

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
