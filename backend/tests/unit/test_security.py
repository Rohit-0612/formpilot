import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

# 65 bytes: long enough for HS512, so the algorithm test fails on the algorithm, not the key.
SECRET = "unit-test-secret-" + "s" * 48
USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
TTL = timedelta(minutes=60)


# --- passwords -----------------------------------------------------------------


def test_hash_round_trip() -> None:
    hashed = hash_password("correct horse battery")

    assert hashed.startswith("$argon2id$")
    assert "correct horse battery" not in hashed
    assert verify_password(hashed, "correct horse battery")


def test_wrong_password_is_rejected() -> None:
    assert not verify_password(hash_password("correct horse battery"), "wrong horse battery")


def test_hashes_are_salted() -> None:
    assert hash_password("same password") != hash_password("same password")


def test_malformed_hash_is_rejected_not_raised() -> None:
    assert not verify_password("not-an-argon2-hash", "anything")


# --- tokens --------------------------------------------------------------------


def test_token_round_trip() -> None:
    token = create_access_token(USER_ID, SECRET, TTL)

    assert decode_access_token(token, SECRET) == USER_ID


def test_expired_token_is_rejected() -> None:
    issued = datetime.now(UTC) - timedelta(hours=2)
    token = create_access_token(USER_ID, SECRET, TTL, now=issued)

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, SECRET)


def test_tampered_token_is_rejected() -> None:
    header, payload, signature = create_access_token(USER_ID, SECRET, TTL).split(".")
    flipped = signature[:-2] + ("A" if signature[-2] != "A" else "B") + signature[-1]

    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{payload}.{flipped}", SECRET)


def test_token_signed_with_another_secret_is_rejected() -> None:
    token = create_access_token(USER_ID, "another-secret-" + "o" * 32, TTL)

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, SECRET)


@pytest.mark.parametrize("algorithm", ["HS512", "none"])
def test_other_algorithms_are_rejected(algorithm: str) -> None:
    now = datetime.now(UTC)
    claims = {"sub": str(USER_ID), "iat": now, "exp": now + TTL}
    key = SECRET if algorithm != "none" else None
    token = jwt.encode(claims, key, algorithm=algorithm)

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, SECRET)


@pytest.mark.parametrize(
    "claims",
    [
        {"iat": 0, "exp": 9_999_999_999},  # no sub
        {"sub": "not-a-uuid", "iat": 0, "exp": 9_999_999_999},
        {"sub": str(USER_ID), "iat": 0},  # no exp
    ],
)
def test_tokens_with_bad_claims_are_rejected(claims: dict) -> None:
    token = jwt.encode(claims, SECRET, algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, SECRET)


def test_garbage_is_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("not.a.jwt", SECRET)
