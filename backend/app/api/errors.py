"""Error responses that never echo request values back.

FastAPI's default 422 body includes each invalid field's "input" (e.g. the rejected password).
Later phases validate Aadhaar/PAN values, so inputs are stripped from every validation error.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_DROPPED_ERROR_KEYS = {"input", "url"}


def _sanitize(error: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in error.items() if key not in _DROPPED_ERROR_KEYS}


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [_sanitize(error) for error in exc.errors()]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(errors)},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
