"""The API's job queue connects on first use, once, and a failure is a 503 (approved Step 8)."""

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api import deps
from app.config import Settings
from app.main import create_app


class _FakePool:
    closed = False

    async def aclose(self) -> None:
        self.closed = True


def test_startup_does_not_connect_and_the_first_use_connects_once(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[_FakePool] = []

    async def fake_create_queue(queue_settings: object) -> _FakePool:
        await asyncio.sleep(0.01)  # concurrent first uses must still create one pool
        created.append(_FakePool())
        return created[-1]

    monkeypatch.setattr(deps, "create_queue", fake_create_queue)
    app = create_app(settings)

    with TestClient(app) as client:
        assert created == []  # nothing at startup
        request = Request({"type": "http", "app": app})

        async def first_uses() -> list[object]:
            return list(await asyncio.gather(*(deps.get_queue(request) for _ in range(5))))

        queues = client.portal.call(first_uses)

        assert len(created) == 1
        assert all(queue is created[0] for queue in queues)
    assert created[0].closed  # closed at shutdown


def test_an_unreachable_queue_is_a_503(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    async def unreachable(queue_settings: object) -> None:
        raise ConnectionError("redis://127.0.0.1:9 refused")

    monkeypatch.setattr(deps, "create_queue", unreachable)
    app = create_app(settings)

    with TestClient(app) as client:
        request = Request({"type": "http", "app": app})
        with pytest.raises(HTTPException) as excinfo:
            client.portal.call(deps.get_queue, request)

    assert excinfo.value.status_code == 503
    assert app.state.queue is None  # the next request tries again
