"""Request ID, standard headers and the last-resort 500 (docs/06 §1, §3.1)."""

import time
from uuid import uuid4

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dawalink.api.errors import ErrorCode, error_response

log = structlog.get_logger(__name__)

# Load balancers call this every few seconds; a healthy answer isn't worth a log line.
QUIET_PATH = "/api/v1/health"


class RequestContextMiddleware:
    """Outermost: names each request, stamps every response, and logs one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        started = time.perf_counter()

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["Cache-Control"] = "no-store"
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_headers)
            finally:
                if scope["path"] != QUIET_PATH or status >= 400:
                    # The path only: query strings can hold what a client searched for.
                    log.info(
                        "request",
                        method=scope["method"],
                        path=scope["path"],
                        status=status,
                        duration_ms=round((time.perf_counter() - started) * 1000, 1),
                    )


class UnhandledErrorMiddleware:
    """Innermost: turns an unexpected exception into the standard 500.

    It sits inside the CORS middleware, so the browser can read the error. Nothing internal
    goes into the response: the stack trace stays in the logs, found by `request_id`.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            request_id = str(scope.get("state", {}).get("request_id", ""))
            log.exception("unhandled_error", request_id=request_id, path=scope["path"])
            if response_started:
                raise
            response = error_response(ErrorCode.INTERNAL_ERROR, request_id)
            await response(scope, receive, send)
