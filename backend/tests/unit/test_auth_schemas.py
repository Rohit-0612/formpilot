import pytest
from pydantic import ValidationError

from app.api.schemas.auth import LoginRequest, RegisterRequest

EMAIL = "asha@example.com"


def test_seven_character_password_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 8 characters"):
        RegisterRequest(email=EMAIL, password="1234567")


def test_eight_character_password_is_accepted() -> None:
    assert RegisterRequest(email=EMAIL, password="12345678").password == "12345678"


def test_overlong_password_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at most 128 characters"):
        RegisterRequest(email=EMAIL, password="x" * 129)


def test_invalid_email_is_rejected() -> None:
    with pytest.raises(ValidationError, match="email"):
        RegisterRequest(email="not-an-email", password="12345678")


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        RegisterRequest(email=EMAIL, password="12345678", is_admin=True)  # type: ignore[call-arg]


def test_login_does_not_enforce_the_minimum_length() -> None:
    # A short wrong password must get the same 401 as any other wrong password.
    assert LoginRequest(email=EMAIL, password="short").password == "short"
