"""Storage for uploaded forms and rendered outputs (interface in base.py)."""

from app.config import Settings
from app.storage.base import Storage
from app.storage.local import LocalStorage


def make_storage(settings: Settings) -> Storage:
    """The configured storage. v1 has only the local filesystem (SPEC §7)."""
    return LocalStorage(settings.storage_root)
