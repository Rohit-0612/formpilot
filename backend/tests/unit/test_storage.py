import os
import stat
from pathlib import Path

import pytest

from app.storage.base import InvalidStorageKeyError, ObjectNotFoundError, validate_key
from app.storage.local import LocalStorage

KEY = "documents/5f0c6d1e-0000-4000-8000-000000000001/original.pdf"
PDF = b"%PDF-1.7 synthetic test bytes"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


@pytest.fixture
def storage(root: Path) -> LocalStorage:
    return LocalStorage(root)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# --- round trip ----------------------------------------------------------------


async def test_put_then_get_round_trip(storage: LocalStorage) -> None:
    await storage.put(KEY, PDF)

    assert await storage.get(KEY) == PDF
    assert await storage.exists(KEY)


async def test_put_overwrites(storage: LocalStorage) -> None:
    await storage.put(KEY, PDF)
    await storage.put(KEY, b"second version")

    assert await storage.get(KEY) == b"second version"


async def test_empty_object_is_allowed(storage: LocalStorage) -> None:
    await storage.put("outputs/empty.bin", b"")

    assert await storage.get("outputs/empty.bin") == b""


async def test_root_is_created_lazily(storage: LocalStorage, root: Path) -> None:
    assert not root.exists()

    await storage.put(KEY, PDF)

    assert root.is_dir()


# --- missing objects ---------------------------------------------------------------


async def test_get_missing_raises_not_found(storage: LocalStorage) -> None:
    with pytest.raises(ObjectNotFoundError):
        await storage.get(KEY)


async def test_get_of_a_prefix_is_not_found(storage: LocalStorage) -> None:
    await storage.put(KEY, PDF)

    with pytest.raises(ObjectNotFoundError):
        await storage.get("documents")


async def test_exists_is_false_for_missing_keys_and_prefixes(storage: LocalStorage) -> None:
    await storage.put(KEY, PDF)

    assert not await storage.exists("documents/other.pdf")
    assert not await storage.exists("documents")


# --- deletion ------------------------------------------------------------------------


async def test_delete(storage: LocalStorage) -> None:
    await storage.put(KEY, PDF)

    await storage.delete(KEY)

    assert not await storage.exists(KEY)


async def test_delete_missing_is_a_no_op(storage: LocalStorage) -> None:
    await storage.delete(KEY)  # does not raise


async def test_delete_of_a_prefix_is_a_no_op(storage: LocalStorage) -> None:
    await storage.put(KEY, PDF)

    await storage.delete("documents")

    assert await storage.exists(KEY)


async def test_delete_prefix_removes_everything_under_it(storage: LocalStorage) -> None:
    await storage.put("documents/abc/original.pdf", PDF)
    await storage.put("documents/abc/pages/0.png", b"png")
    await storage.put("documents/abcd/original.pdf", PDF)  # same string prefix, other document

    await storage.delete_prefix("documents/abc")

    assert not await storage.exists("documents/abc/original.pdf")
    assert not await storage.exists("documents/abc/pages/0.png")
    assert await storage.exists("documents/abcd/original.pdf")


async def test_delete_prefix_does_not_delete_a_file_with_that_name(storage: LocalStorage) -> None:
    await storage.put("documents/abc", PDF)

    await storage.delete_prefix("documents/abc")

    assert await storage.exists("documents/abc")


async def test_delete_prefix_missing_is_a_no_op(storage: LocalStorage) -> None:
    await storage.delete_prefix("documents/never-created")  # does not raise


# --- key validation and path traversal ---------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/etc/passwd",
        "../outside.pdf",
        "documents/../../outside.pdf",
        "documents/./original.pdf",
        "documents//original.pdf",
        "documents/",
        "documents\\original.pdf",
        "documents/.hidden",
        "documents/with space.pdf",
        "documents/naïve.pdf",
        "a" * 1025,
    ],
)
async def test_invalid_keys_are_rejected_everywhere(storage: LocalStorage, key: str) -> None:
    for operation in (
        storage.put(key, PDF),
        storage.get(key),
        storage.exists(key),
        storage.delete(key),
        storage.delete_prefix(key),
    ):
        with pytest.raises(InvalidStorageKeyError):
            await operation


def test_invalid_key_error_does_not_echo_the_key() -> None:
    with pytest.raises(InvalidStorageKeyError) as excinfo:
        validate_key("documents/asha verma aadhaar.pdf")

    assert "asha" not in str(excinfo.value)


async def test_symlink_leading_outside_the_root_is_rejected(
    storage: LocalStorage, root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    await storage.put("placeholder.bin", b"")  # creates the root
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidStorageKeyError):
        await storage.put("escape/stolen.pdf", PDF)
    assert list(outside.iterdir()) == []


# --- atomic writes and permissions --------------------------------------------------


async def test_put_leaves_no_temp_files(storage: LocalStorage, root: Path) -> None:
    await storage.put(KEY, PDF)

    files = [path.name for path in root.rglob("*") if path.is_file()]
    assert files == ["original.pdf"]


async def test_failed_write_keeps_the_old_content_and_cleans_up(
    storage: LocalStorage, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await storage.put(KEY, PDF)

    def fail_replace(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk full"):
        await storage.put(KEY, b"new content that never lands")
    monkeypatch.undo()

    assert await storage.get(KEY) == PDF
    assert [path.name for path in root.rglob("*") if path.is_file()] == ["original.pdf"]


async def test_files_and_directories_are_owner_only(storage: LocalStorage, root: Path) -> None:
    await storage.put(KEY, PDF)

    file_path = root / KEY
    assert _mode(file_path) == 0o600
    assert _mode(root) == 0o700
    assert _mode(file_path.parent) == 0o700
    assert _mode(file_path.parent.parent) == 0o700
