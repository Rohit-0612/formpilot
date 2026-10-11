"""Storage on the local filesystem (a Docker volume in compose)."""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from app.storage.base import (
    InvalidStorageKeyError,
    ObjectNotFoundError,
    Storage,
    validate_key,
)

# Uploaded forms are private: owner-only permissions.
_DIR_MODE = 0o700
_FILE_MODE = 0o600


class LocalStorage(Storage):
    def __init__(self, root: Path) -> None:
        self._root = root

    # --- public API (blocking filesystem work runs in a thread) ------------------

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._put, self._path(key), data)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except (FileNotFoundError, IsADirectoryError):
            raise ObjectNotFoundError("storage object not found") from None

    async def exists(self, key: str) -> bool:
        path = self._path(key)
        return await asyncio.to_thread(path.is_file)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(_delete_file, self._path(key))

    async def delete_prefix(self, prefix: str) -> None:
        await asyncio.to_thread(_delete_tree, self._path(prefix))

    # --- internals ---------------------------------------------------------------

    def _resolved_root(self) -> Path:
        self._ensure_dir(self._root)
        return self._root.resolve()

    def _path(self, key: str) -> Path:
        root = self._resolved_root()
        path = root.joinpath(*validate_key(key))
        # Defence in depth: a symlink inside the root must not lead outside it.
        if not path.resolve().is_relative_to(root):
            raise InvalidStorageKeyError("storage key resolves outside the storage root")
        return path

    @staticmethod
    def _ensure_dir(directory: Path) -> None:
        missing: list[Path] = []
        current = directory
        while not current.exists():
            missing.append(current)
            current = current.parent
        for path in reversed(missing):
            path.mkdir(mode=_DIR_MODE, exist_ok=True)
            path.chmod(_DIR_MODE)  # mkdir's mode is reduced by the umask

    def _put(self, path: Path, data: bytes) -> None:
        self._ensure_dir(path.parent)
        # Write to a temp file in the same directory, then rename over the target: readers see
        # either the old or the new content, never a partial file. mkstemp creates it as 0600.
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.chmod(tmp_name, _FILE_MODE)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


def _delete_file(path: Path) -> None:
    # A directory is not an object, so "deleting" it is a no-op like any missing key.
    if path.is_file():
        path.unlink(missing_ok=True)


def _delete_tree(path: Path) -> None:
    # Only what lies under prefix + "/"; a file named exactly like the prefix is not touched.
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
