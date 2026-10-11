import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_health_service
from app.config import Settings
from app.main import create_app
from app.services.health import HealthReport, HealthService


async def _ok() -> None:
    return None


async def _fail() -> None:
    raise ConnectionError("connection refused to host db:5432 user=secret")


async def _hang() -> None:
    await asyncio.sleep(10)


# --- service -----------------------------------------------------------------


async def test_all_probes_ok() -> None:
    report = await HealthService(_ok, _ok, timeout_seconds=1).check()

    assert report == HealthReport(db="ok", redis="ok")
    assert report.ok


async def test_failing_database_probe_is_reported() -> None:
    report = await HealthService(_fail, _ok, timeout_seconds=1).check()

    assert report == HealthReport(db="error", redis="ok")
    assert not report.ok


async def test_hanging_redis_probe_times_out() -> None:
    report = await HealthService(_ok, _hang, timeout_seconds=0.05).check()

    assert report == HealthReport(db="ok", redis="error")


# --- route -------------------------------------------------------------------


class _FixedHealthService(HealthService):
    def __init__(self, report: HealthReport) -> None:
        self._report = report

    async def check(self) -> HealthReport:
        return self._report


@pytest.fixture
def client_for(settings: Settings) -> Iterator:
    clients: list[TestClient] = []

    def make(report: HealthReport) -> TestClient:
        app = create_app(settings)
        app.dependency_overrides[get_health_service] = lambda: _FixedHealthService(report)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def test_health_ok_returns_200(client_for) -> None:
    response = client_for(HealthReport(db="ok", redis="ok")).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "redis": "ok"}


@pytest.mark.parametrize(
    ("report", "body"),
    [
        (
            HealthReport(db="error", redis="ok"),
            {"status": "degraded", "db": "error", "redis": "ok"},
        ),
        (
            HealthReport(db="ok", redis="error"),
            {"status": "degraded", "db": "ok", "redis": "error"},
        ),
    ],
)
def test_health_degraded_returns_503(client_for, report: HealthReport, body: dict) -> None:
    response = client_for(report).get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == body


def test_response_carries_request_id(client_for) -> None:
    client = client_for(HealthReport(db="ok", redis="ok"))

    generated = client.get("/api/v1/health")
    echoed = client.get("/api/v1/health", headers={"X-Request-ID": "abc-123"})
    rejected = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\nforged=1"})

    assert len(generated.headers["X-Request-ID"]) == 32
    assert echoed.headers["X-Request-ID"] == "abc-123"
    assert rejected.headers["X-Request-ID"] != "bad id\nforged=1"
