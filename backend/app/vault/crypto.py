"""Fernet encryption with the vault key (SPEC §7, §11): the profile vault and, field by field, the
values of sensitive and phone types in stored IR versions (decision P4-D5).

Fernet is authenticated: a token changed in the database fails to decrypt instead of returning
garbage. This protects a database dump; it is not end-to-end encryption (the server holds the key).
Errors never contain a value or the key.
"""

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr


class VaultError(Exception):
    """A token that cannot be decrypted with the vault key (changed, or made with another key)."""


def check_vault_key(key: str) -> None:
    """Raises ValueError unless `key` is a Fernet key (32 bytes, URL-safe base64)."""
    try:
        Fernet(key.encode())
    except (ValueError, TypeError):
        raise ValueError(
            "VAULT_KEY must be a Fernet key (32 bytes, URL-safe base64); generate one with "
            "`openssl rand -base64 32 | tr '+/' '-_'`"
        ) from None


class VaultCipher:
    def __init__(self, key: SecretStr) -> None:
        self._fernet = Fernet(key.get_secret_value().encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except (InvalidToken, ValueError, TypeError):
            raise VaultError("the value cannot be decrypted with the vault key") from None
