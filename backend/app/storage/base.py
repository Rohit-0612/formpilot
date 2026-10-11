"""Storage for uploaded forms and rendered outputs.

Keys are relative, "/"-separated paths such as "documents/<uuid>/original.pdf". Each segment uses
only letters, digits, ".", "_" and "-", and must not start with "." (no "..", no hidden files).
Implementations must reject anything else with InvalidStorageKeyError.
"""

import re
from abc import ABC, abstractmethod

_SEGMENT = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,254}$")
MAX_KEY_LENGTH = 1024


class StorageError(Exception):
    pass


class InvalidStorageKeyError(StorageError, ValueError):
    pass


class ObjectNotFoundError(StorageError, KeyError):
    pass


def validate_key(key: str) -> list[str]:
    """Return the key's segments, or raise InvalidStorageKeyError. Never echoes the key."""
    if not key or len(key) > MAX_KEY_LENGTH:
        raise InvalidStorageKeyError("storage key is empty or too long")
    segments = key.split("/")
    if not all(_SEGMENT.fullmatch(segment) for segment in segments):
        raise InvalidStorageKeyError("storage key has an invalid segment")
    return segments


class Storage(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes) -> None:
        """Store data under key atomically, replacing any existing object."""

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Return the object's bytes, or raise ObjectNotFoundError."""

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete one object. Deleting a missing object is not an error."""

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> None:
        """Delete every object whose key starts with prefix + "/" (e.g. one document's files).

        The prefix ends at a segment boundary: "documents/ab" never touches "documents/abc/...".
        """
