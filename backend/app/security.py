"""Password hashing (Argon2id) and session tokens (JWT, HS256)."""

import uuid
from datetime import UTC, datetime, timedelta
from functools import cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

JWT_ALGORITHM = "HS256"

# argon2-cffi defaults: Argon2id with the RFC 9106 low-memory profile.
_hasher = PasswordHasher()


class InvalidTokenError(Exception):
    """The session token is missing required claims, expired, tampered with or malformed."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@cache
def _dummy_hash() -> str:
    return _hasher.hash("timing-equaliser-not-a-password")


def burn_verify_time(password: str) -> None:
    """Spend the same time as a real verify, so unknown emails are not revealed by timing."""
    verify_password(_dummy_hash(), password)


def create_access_token(
    user_id: uuid.UUID, secret: str, ttl: timedelta, now: datetime | None = None
) -> str:
    issued_at = now or datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": issued_at, "exp": issued_at + ttl}
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, secret: str) -> uuid.UUID:
    """Return the user id from a valid token, else raise InvalidTokenError."""
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise InvalidTokenError(type(exc).__name__) from exc
