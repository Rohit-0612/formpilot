"""Vault encryption (SPEC §11, decision P4-D5): Fernet round trip, tampering, wrong key."""

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.vault.crypto import VaultCipher, VaultError, check_vault_key
from tests.conftest import TEST_VAULT_KEY

VALUE = "ABCDE1234F"  # synthetic PAN-shaped value


@pytest.fixture
def cipher() -> VaultCipher:
    return VaultCipher(SecretStr(TEST_VAULT_KEY))


def test_round_trip_and_ciphertext_hides_the_value(cipher: VaultCipher) -> None:
    token = cipher.encrypt(VALUE)

    assert VALUE not in token
    assert cipher.decrypt(token) == VALUE
    assert cipher.encrypt(VALUE) != token  # a fresh IV every time


def test_unicode_values_round_trip(cipher: VaultCipher) -> None:
    assert cipher.decrypt(cipher.encrypt("राम कुमार")) == "राम कुमार"


def test_a_changed_token_is_refused_without_showing_anything(cipher: VaultCipher) -> None:
    token = cipher.encrypt(VALUE)
    changed = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]

    with pytest.raises(VaultError) as error:
        cipher.decrypt(changed)
    assert VALUE not in str(error.value) and changed not in str(error.value)
    assert error.value.__cause__ is None and error.value.__suppress_context__


def test_another_key_cannot_decrypt(cipher: VaultCipher) -> None:
    other = VaultCipher(SecretStr(Fernet.generate_key().decode()))

    with pytest.raises(VaultError):
        other.decrypt(cipher.encrypt(VALUE))


@pytest.mark.parametrize("key", ["", "short", "a" * 44])
def test_check_vault_key_rejects_non_fernet_keys(key: str) -> None:
    with pytest.raises(ValueError, match="Fernet key"):
        check_vault_key(key)


def test_check_vault_key_accepts_a_generated_key() -> None:
    check_vault_key(Fernet.generate_key().decode())
