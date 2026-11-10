"""The one error format and its stable codes (docs/06 §3). Codes are added with their features."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


HTTP_STATUS: Mapping[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
}

# Plain English, safe to show. The website shows its own wording per code (docs/11 §7).
DEFAULT_MESSAGE: Mapping[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "Some fields are missing or invalid.",
    ErrorCode.NOT_FOUND: "We couldn't find that.",
    ErrorCode.METHOD_NOT_ALLOWED: "That action isn't available here.",
    ErrorCode.INTERNAL_ERROR: "Something went wrong on our side. Please try again.",
    ErrorCode.SERVICE_UNAVAILABLE: "DawaLink is temporarily unavailable. Please try again.",
}


class ApiError(Exception):
    """Raised by endpoints and services to answer with a catalog code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.message = message or DEFAULT_MESSAGE[code]
        self.details = dict(details or {})


def error_response(
    code: ErrorCode,
    request_id: str,
    *,
    message: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=HTTP_STATUS[code],
        content={
            "error": {
                "code": code.value,
                "message": message or DEFAULT_MESSAGE[code],
                "details": dict(details or {}),
                "request_id": request_id,
            }
        },
    )


def request_id_of(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


def _field_path(location: tuple[int | str, ...]) -> str:
    """("body", "items", 1, "qty") -> "items[1].qty"."""
    path = ""
    for part in location[1:]:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else part
    return path or str(location[0])


async def _on_api_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ApiError)
    return error_response(
        error.code, request_id_of(request), message=error.message, details=error.details
    )


async def _on_validation_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    fields = [
        {"field": _field_path(tuple(item["loc"])), "problem": str(item["msg"])}
        for item in error.errors()
    ]
    return error_response(
        ErrorCode.VALIDATION_ERROR, request_id_of(request), details={"fields": fields}
    )


async def _on_http_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, StarletteHTTPException)
    by_status = {404: ErrorCode.NOT_FOUND, 405: ErrorCode.METHOD_NOT_ALLOWED}
    code = by_status.get(error.status_code)
    if code is None:
        # Our own code raises ApiError, so any other status here is unexpected.
        log.error(
            "unexpected_http_error",
            request_id=request_id_of(request),
            path=request.url.path,
            status=error.status_code,
        )
        code = ErrorCode.INTERNAL_ERROR
    return error_response(code, request_id_of(request))


async def _on_database_error(request: Request, error: Exception) -> JSONResponse:
    """The database is unreachable or cut a statement off: safe to retry (FX-10, FX-11)."""
    log.error(
        "database_unavailable",
        request_id=request_id_of(request),
        path=request.url.path,
        error=type(error).__name__,
    )
    return error_response(ErrorCode.SERVICE_UNAVAILABLE, request_id_of(request))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _on_api_error)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_error)
    app.add_exception_handler(OperationalError, _on_database_error)
