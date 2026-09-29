"""Error responses and logs must never contain request values [A5]."""

import io

from fastapi.testclient import TestClient

from app.config import Settings
from app.logging import configure_logging
from app.main import create_app

EMAIL = "asha.verma@example.com"
PASSWORD = "short77"


def test_validation_errors_do_not_echo_the_input(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert EMAIL not in response.text
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", "password"]
    assert error["type"] == "string_too_short"
    assert "input" not in error


def test_unhandled_errors_log_type_and_stack_but_not_the_message(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/api/v1/boom")
    async def boom() -> None:
        raise ValueError(f"Key (email)=({EMAIL}) already exists")

    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/boom", headers={"X-Request-ID": "req-boom"})

    output = stream.getvalue()
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error", "request_id": "req-boom"}
    assert EMAIL not in response.text
    assert EMAIL not in output
    assert '"exc_type": "ValueError"' in output
    assert "test_errors.py" in output  # the stack frames are there for debugging
