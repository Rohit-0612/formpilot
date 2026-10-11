import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SESSION_COOKIE
from app.config import Settings
from app.db.models import User
from app.db.session import get_session
from app.logging import configure_logging
from app.main import create_app
from app.security import create_access_token

# Synthetic credentials only.
EMAIL = "asha.verma@example.com"
PASSWORD = "correct-horse-7"
AUTH = "/api/v1/auth"


@pytest.fixture
def log_stream() -> io.StringIO:
    return io.StringIO()


@pytest.fixture
async def client(
    settings: Settings, db_session: AsyncSession, log_stream: io.StringIO
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    configure_logging("INFO", json=True, stream=log_stream)

    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _register(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD):
    return await client.post(f"{AUTH}/register", json={"email": email, "password": password})


async def _login(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD):
    return await client.post(f"{AUTH}/login", json={"email": email, "password": password})


# --- happy path ----------------------------------------------------------------


async def test_register_login_me_logout(client: AsyncClient, settings: Settings) -> None:
    registered = await _register(client)
    assert registered.status_code == 201
    user = registered.json()
    assert user == {"id": user["id"], "email": EMAIL}
    assert SESSION_COOKIE not in registered.headers.get("set-cookie", "")  # no auto-login

    logged_in = await _login(client)
    assert logged_in.status_code == 200
    assert logged_in.json() == user
    cookie = logged_in.headers["set-cookie"].lower()
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert f"max-age={settings.jwt_ttl_minutes * 60}" in cookie
    assert "secure" not in cookie  # COOKIE_SECURE=false in tests

    me = await client.get(f"{AUTH}/me")
    assert me.status_code == 200
    assert me.json() == user

    logged_out = await client.post(f"{AUTH}/logout")
    assert logged_out.status_code == 204
    assert f'{SESSION_COOKIE}=""' in logged_out.headers["set-cookie"]
    assert (await client.get(f"{AUTH}/me")).status_code == 401


async def test_secure_flag_is_set_when_configured(
    settings: Settings, db_session: AsyncSession
) -> None:
    app = create_app(settings.model_copy(update={"cookie_secure": True}))

    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as c:
        await _register(c)
        response = await _login(c)

    assert "secure" in response.headers["set-cookie"].lower()


async def test_password_is_stored_as_argon2id_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _register(client)

    stored = await db_session.scalar(select(User.password_hash).where(User.email == EMAIL))

    assert stored is not None
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


# --- registration rules --------------------------------------------------------


async def test_email_is_case_insensitive(client: AsyncClient) -> None:
    registered = await _register(client, email="Asha.Verma@Example.COM")

    assert registered.json()["email"] == EMAIL
    assert (await _login(client, email="ASHA.VERMA@example.com")).status_code == 200


async def test_duplicate_email_is_409_in_any_case(client: AsyncClient) -> None:
    await _register(client)

    duplicate = await _register(client, email=EMAIL.upper())

    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Email already registered"}


async def test_seven_character_password_is_422_and_not_echoed(client: AsyncClient) -> None:
    response = await _register(client, password="short77")

    assert response.status_code == 422
    assert "short77" not in response.text
    assert (await _register(client, password="eight888")).status_code == 201


# --- login failures ------------------------------------------------------------


async def test_wrong_password_and_unknown_email_look_the_same(client: AsyncClient) -> None:
    await _register(client)

    wrong_password = await _login(client, password="wrong-password-1")
    unknown_email = await _login(client, email="nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == {"detail": "Invalid email or password"}
    assert "set-cookie" not in wrong_password.headers


# --- /me rejects bad sessions --------------------------------------------------


async def test_me_without_cookie_is_401(client: AsyncClient) -> None:
    response = await client.get(f"{AUTH}/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


@pytest.mark.parametrize("kind", ["garbage", "expired", "wrong_secret", "unknown_user"])
async def test_me_with_bad_session_cookie_is_401(
    client: AsyncClient, settings: Settings, kind: str
) -> None:
    user_id = uuid.UUID((await _register(client)).json()["id"])
    secret = settings.jwt_secret.get_secret_value()
    ttl = timedelta(minutes=5)
    token = {
        "garbage": "not-a-token",
        "expired": create_access_token(user_id, secret, ttl, now=datetime.now(UTC) - 2 * ttl),
        "wrong_secret": create_access_token(user_id, "x" * 64, ttl),
        "unknown_user": create_access_token(uuid.uuid4(), secret, ttl),
    }[kind]

    client.cookies.set(SESSION_COOKIE, token)
    response = await client.get(f"{AUTH}/me")

    assert response.status_code == 401


# --- logging rules [A5] ----------------------------------------------------------


async def test_logs_never_contain_email_or_password(
    client: AsyncClient, log_stream: io.StringIO
) -> None:
    user_id = (await _register(client)).json()["id"]
    await _register(client)  # duplicate
    await _register(client, email="other@example.com", password="short")  # 422
    await _login(client, password="wrong-password-1")  # wrong password
    await _login(client, email="nobody@example.com")  # unknown email
    await _login(client)
    await client.get(f"{AUTH}/me")
    await client.post(f"{AUTH}/logout")

    output = log_stream.getvalue().lower()
    for secret_value in (EMAIL, "other@example.com", "nobody@example.com", PASSWORD, "short"):
        assert secret_value.lower() not in output, secret_value
    assert "example.com" not in output
    assert user_id in output  # logs carry the user id instead
    for event in ("user_registered", "registration_rejected", "login_failed", "user_logged_in"):
        assert f'"event": "{event}"' in output
