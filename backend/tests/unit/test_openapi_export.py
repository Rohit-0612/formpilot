import json
from pathlib import Path

import pytest

from app.openapi_export import main, openapi_schema


def test_schema_builds_without_any_environment(clean_env: pytest.MonkeyPatch) -> None:
    schema = openapi_schema()

    assert schema["info"]["title"] == "FormPilot API"
    assert {
        "/api/v1/health",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
    } <= set(schema["paths"])


def test_cookie_auth_is_declared() -> None:
    schemes = openapi_schema()["components"]["securitySchemes"]

    assert {"type": "apiKey", "in": "cookie", "name": "fp_session"}.items() <= next(
        iter(schemes.values())
    ).items()


def test_main_writes_the_schema_to_a_file(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"

    assert main([str(out)]) == 0
    assert json.loads(out.read_text())["paths"]


def test_output_is_deterministic() -> None:
    assert json.dumps(openapi_schema()) == json.dumps(openapi_schema())
