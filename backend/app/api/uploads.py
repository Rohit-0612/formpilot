"""Reading a multipart upload with the size cap enforced while the body arrives (decision D4).

Starlette's form parser reads the whole body before a route sees the file, so checking the
file's size afterwards caps nothing. Instead:
1. a declared Content-Length above the cap is refused before anything is read;
2. the body is counted as it is received, and reading stops once it passes the cap, which
   also catches a missing or false Content-Length;
3. the file part itself is checked against the exact limit.
"""

from dataclasses import dataclass

from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException
from starlette.requests import Request
from starlette.types import Message

# Room for the multipart framing (boundaries, part headers) around the file itself.
MULTIPART_OVERHEAD = 64 * 1024
FILE_FIELD = "file"


class UploadTooLargeError(Exception):
    pass


class InvalidUploadError(Exception):
    """Not a multipart body with exactly one file in the `file` field."""


@dataclass(frozen=True)
class Upload:
    filename: str | None
    data: bytes


async def read_upload(request: Request, max_bytes: int) -> Upload:
    body_cap = max_bytes + MULTIPART_OVERHEAD
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > body_cap:
        raise UploadTooLargeError

    received = 0

    async def counting_receive() -> Message:
        nonlocal received
        message = await request.receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > body_cap:
                raise UploadTooLargeError
        return message

    limited = Request(request.scope, receive=counting_receive)
    try:
        form = await limited.form(max_files=1, max_fields=1)
    except MultiPartException:
        raise InvalidUploadError from None
    try:
        files = form.getlist(FILE_FIELD)
        if len(files) != 1 or not isinstance(files[0], UploadFile):
            raise InvalidUploadError
        data = await files[0].read(max_bytes + 1)
        if len(data) > max_bytes:
            raise UploadTooLargeError
        return Upload(files[0].filename, data)
    finally:
        await form.close()
