"""Upload checks done by the API (decision D3): size cap while reading, magic bytes, file names,
and the readable job error messages."""

import pytest
from starlette.requests import Request
from starlette.types import Message

from app.api.uploads import (
    MULTIPART_OVERHEAD,
    InvalidUploadError,
    UploadTooLargeError,
    read_upload,
)
from app.services.documents import (
    DEFAULT_FILENAME,
    clean_filename,
    job_error_message,
    looks_like_pdf,
)

BOUNDARY = "formpilot-test-boundary"
PDF = b"%PDF-1.7\n" + b"0" * 1000


def _part(data: bytes, field: str = "file", filename: str | None = "form.pdf") -> bytes:
    disposition = f'form-data; name="{field}"' + (f'; filename="{filename}"' if filename else "")
    return (
        (
            f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\n"
            "Content-Type: application/pdf\r\n\r\n"
        ).encode()
        + data
        + b"\r\n"
    )


def _body(*parts: bytes) -> bytes:
    return b"".join(parts) + f"--{BOUNDARY}--\r\n".encode()


class _Client:
    """Feeds a body to read_upload in chunks, as an ASGI server would, and records reads."""

    def __init__(
        self,
        body: bytes,
        *,
        content_length: int | None = None,
        declare_length: bool = True,
        content_type: str = f"multipart/form-data; boundary={BOUNDARY}",
        chunk: int = 4096,
    ) -> None:
        self.chunks = [body[i : i + chunk] for i in range(0, len(body), chunk)] or [b""]
        self.read = 0
        headers = [(b"content-type", content_type.encode())]
        if declare_length:
            length = len(body) if content_length is None else content_length
            headers.append((b"content-length", str(length).encode()))
        scope = {"type": "http", "method": "POST", "path": "/", "headers": headers}
        self.request = Request(scope, receive=self._receive)
        self._next = 0

    async def _receive(self) -> Message:
        if self._next >= len(self.chunks):
            return {"type": "http.disconnect"}
        chunk = self.chunks[self._next]
        self._next += 1
        self.read += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": self._next < len(self.chunks)}


# --- size cap ------------------------------------------------------------------------------


async def test_a_file_of_exactly_the_limit_is_accepted() -> None:
    upload = await read_upload(_Client(_body(_part(PDF))).request, max_bytes=len(PDF))

    assert upload.data == PDF
    assert upload.filename == "form.pdf"


async def test_one_byte_over_the_limit_is_refused() -> None:
    with pytest.raises(UploadTooLargeError):
        await read_upload(_Client(_body(_part(PDF))).request, max_bytes=len(PDF) - 1)


async def test_a_declared_length_over_the_cap_is_refused_before_reading() -> None:
    client = _Client(_body(_part(PDF)), content_length=10 * 1024 * 1024)

    with pytest.raises(UploadTooLargeError):
        await read_upload(client.request, max_bytes=len(PDF))

    assert client.read == 0


@pytest.mark.parametrize("declare_length", [True, False])
async def test_a_false_or_missing_length_is_caught_while_reading(declare_length: bool) -> None:
    big = b"%PDF-" + b"0" * (2 * 1024 * 1024)
    client = _Client(_body(_part(big)), content_length=100, declare_length=declare_length)
    max_bytes = 100 * 1024

    with pytest.raises(UploadTooLargeError):
        await read_upload(client.request, max_bytes=max_bytes)

    # Reading stopped within one chunk of the cap, long before the 2 MB body was read.
    assert client.read <= max_bytes + MULTIPART_OVERHEAD + 4096


# --- shape of the body ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        _body(_part(PDF), _part(PDF)),  # two files
        _body(_part(PDF, field="document")),  # wrong field name
        _body(_part(b"%PDF-", filename=None)),  # a plain form field, not a file
        _body(),  # no parts
    ],
)
async def test_anything_but_one_file_in_field_file_is_invalid(body: bytes) -> None:
    with pytest.raises(InvalidUploadError):
        await read_upload(_Client(body).request, max_bytes=10 * 1024)


async def test_a_body_that_is_not_multipart_is_invalid() -> None:
    client = _Client(PDF, content_type="application/pdf")

    with pytest.raises(InvalidUploadError):
        await read_upload(client.request, max_bytes=10 * 1024)


# --- magic bytes ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "is_pdf"),
    [
        (b"%PDF-1.7\n", True),
        (b"\xef\xbb\xbf" + b" " * 990 + b"%PDF-1.4", True),  # junk before the header
        (b" " * 1020 + b"%PDF-1.4", False),  # header starts after byte 1024
        (b"\x89PNG\r\n\x1a\n", False),
        (b"%PDF", False),  # incomplete magic
        (b"", False),
    ],
)
def test_magic_bytes(head: bytes, is_pdf: bool) -> None:
    assert looks_like_pdf(head) is is_pdf


# --- file names ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "cleaned"),
    [
        ("form.pdf", "form.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\asha\\scholarship.pdf", "scholarship.pdf"),
        ("a\x00b\nc\td.pdf", "abcd.pdf"),
        ("\u202efdp.exe", "fdp.exe"),  # right-to-left override removed
        ("  form.pdf  ", "form.pdf"),
        ("प्रवेश फ़ॉर्म.pdf", "प्रवेश फ़ॉर्म.pdf"),  # combining marks kept
        ("", DEFAULT_FILENAME),
        (None, DEFAULT_FILENAME),
        ("dir/", DEFAULT_FILENAME),
    ],
)
def test_clean_filename(name: str | None, cleaned: str) -> None:
    assert clean_filename(name) == cleaned


def test_long_file_names_are_cut_to_the_column_size() -> None:
    assert len(clean_filename("a" * 1000 + ".pdf")) == 255


# --- readable job errors -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (None, None),
        ("TooManyPages", "The PDF has more than 50 pages."),
        ("EncryptedPdf", "The PDF is password-protected. Upload a copy without a password."),
        ("UnreadablePdf", "The file could not be read as a PDF."),
        ("Stale", "The analysis was interrupted. Please upload the file again."),
        (
            "Cancelled",
            "The analysis took too long or was interrupted. Please upload the file again.",
        ),
        (
            "EnqueueFailed:ConnectionError",
            "The analysis could not be started. Please upload the file again.",
        ),
        ("KeyError", "The analysis failed."),  # internal errors are not explained
    ],
)
def test_job_error_message(error: str | None, message: str | None) -> None:
    assert job_error_message(error, max_pages=50) == message
