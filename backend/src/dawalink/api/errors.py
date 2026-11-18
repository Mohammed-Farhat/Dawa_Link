"""The one error format and its stable codes (docs/06 §3). Codes are added with their features."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from starlette.exceptions import HTTPException as StarletteHTTPException

from dawalink.services.errors import Code, ServiceError

log = structlog.get_logger(__name__)


class ErrorCode(StrEnum):
    """What the API itself answers. A rule's refusal keeps the service's own code (below)."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    ORIGIN_REJECTED = "ORIGIN_REJECTED"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    RATE_LIMITED = "RATE_LIMITED"
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    BODY_TOO_LARGE = "BODY_TOO_LARGE"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


HTTP_STATUS: Mapping[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.ORIGIN_REJECTED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.IDEMPOTENCY_KEY_REQUIRED: 400,
    ErrorCode.BODY_TOO_LARGE: 413,
    ErrorCode.INVALID_CREDENTIALS: 401,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
}

# The HTTP status of each refusal by a rule (docs/06 §3.2). Anything not listed is 409:
# "not now, not like this", the most common kind. A test compares every status with the
# catalog table of that document, in both directions.
_SERVICE_STATUS: Mapping[Code, int] = {
    Code.NOT_FOUND: 404,
    Code.VALIDATION_ERROR: 422,
    Code.RATE_LIMITED: 429,
    Code.WEAK_PASSWORD: 422,
    Code.SIGNUP_LIMIT: 429,
    Code.ACCOUNT_LOCKED: 429,
    Code.TOKEN_INVALID: 400,
    Code.ACCOUNT_SUSPENDED: 403,
    Code.EMAIL_NOT_VERIFIED: 403,
    Code.CLIENT_PAUSED: 403,
    Code.PHARMACY_NOT_APPROVED: 403,
    Code.PICKUP_DAY_INVALID: 422,
    Code.PRODUCT_NOT_ALLOWED: 422,
    Code.SELECTION_INVALID: 422,
    Code.ASSISTANT_UNAVAILABLE: 503,
    Code.TOKEN_BUDGET_EXCEEDED: 429,
    Code.MESSAGE_TOO_LONG: 422,
    Code.UNITS_INVALID: 422,
    Code.UPLOAD_FAILED: 422,
    Code.FILE_TOO_LARGE: 413,
    Code.PRICE_ABOVE_PUBLIC: 422,
    Code.REASON_REQUIRED: 422,
    # Outside demo mode the demo clock doesn't exist (R-DEMO).
    Code.DEMO_MODE_OFF: 404,
}


def service_status(code: Code) -> int:
    return _SERVICE_STATUS.get(code, 409)


# Plain English, safe to show. The website shows its own wording per code (docs/11 §7).
DEFAULT_MESSAGE: Mapping[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "Some fields are missing or invalid.",
    ErrorCode.UNAUTHENTICATED: "Please log in.",
    ErrorCode.FORBIDDEN: "This account can't do that.",
    ErrorCode.ORIGIN_REJECTED: "This request didn't come from DawaLink's website.",
    ErrorCode.NOT_FOUND: "We couldn't find that.",
    ErrorCode.RATE_LIMITED: "Too many tries. Please wait a minute.",
    ErrorCode.IDEMPOTENCY_KEY_REQUIRED: "This request needs an Idempotency-Key header.",
    ErrorCode.BODY_TOO_LARGE: "This request is too large.",
    ErrorCode.INVALID_CREDENTIALS: "Wrong email or password.",
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


def error_body(
    code: str, message: str, request_id: str, details: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The one error format (docs/06 §3.1), also sent inside the chat stream."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": jsonable_encoder(dict(details or {})),
            "request_id": request_id,
        }
    }


def error_response(
    code: ErrorCode,
    request_id: str,
    *,
    message: str | None = None,
    details: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=HTTP_STATUS[code],
        content=error_body(code.value, message or DEFAULT_MESSAGE[code], request_id, details),
        headers=dict(headers or {}),
    )


def _retry_after(details: Mapping[str, Any]) -> dict[str, str]:
    """`Retry-After` for the refusals that end by themselves (docs/06 §3.2)."""
    seconds = details.get("retry_after_s") or details.get("retry_after")
    return {"Retry-After": str(int(seconds))} if isinstance(seconds, int | float) else {}


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
        error.code,
        request_id_of(request),
        message=error.message,
        details=error.details,
        headers=_retry_after(error.details),
    )


async def _on_service_error(request: Request, error: Exception) -> JSONResponse:
    """A rule said no: its code, its plain message, and what the client may be told."""
    assert isinstance(error, ServiceError)
    return JSONResponse(
        status_code=service_status(error.code),
        content=error_body(error.code.value, error.message, request_id_of(request), error.details),
        headers=_retry_after(error.details),
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
    if error.status_code == 400:
        # The framework's own answer to a body it can't even read as text (bytes that are
        # not UTF-8). It used to end as a server error; found by `tests/api/test_fuzz.py`.
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            request_id_of(request),
            details={"fields": [{"field": "body", "problem": "The body can't be read."}]},
        )
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
    """The database is unreachable, cut a statement off, or has no free connection: safe to
    retry (FX-10, FX-11, FX-12)."""
    log.error(
        "database_unavailable",
        request_id=request_id_of(request),
        path=request.url.path,
        error=type(error).__name__,
    )
    return error_response(ErrorCode.SERVICE_UNAVAILABLE, request_id_of(request))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _on_api_error)
    app.add_exception_handler(ServiceError, _on_service_error)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_error)
    app.add_exception_handler(OperationalError, _on_database_error)
    # No free connection within the wait (FX-12): the same answer, "try again".
    app.add_exception_handler(PoolTimeout, _on_database_error)
