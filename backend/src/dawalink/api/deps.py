"""What endpoints can ask for: the settings, a transaction, and **who is calling**.

The three checks of docs/06 §2.2 start here: `signed_in` finds the caller from the login
token, `as_client` / `as_pharmacist` / `as_admin` check the role. The status gates
(verified, paused, approved) and ownership are checked by the services, where the rules
are.
"""

import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, cast

import structlog
from fastapi import Depends, Header, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from dawalink.agent.turn import Agent
from dawalink.api.errors import ApiError, ErrorCode
from dawalink.api.limits import Limiter
from dawalink.config import Settings
from dawalink.domain.clock import Clock
from dawalink.domain.vocabulary import UserRole
from dawalink.services import auth
from dawalink.services.context import Tx, unit_of_work

log = structlog.get_logger(__name__)


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_engine(request: Request) -> Engine:
    return cast(Engine, request.app.state.engine)


def secret_key(settings: Settings) -> str:
    assert settings.app_secret_key is not None  # checked when the app is built
    return settings.app_secret_key.get_secret_value()


class Work:
    """Opens the transactions of one request. An endpoint commits by leaving the block:

    with work.tx() as tx:
        ...
    """

    def __init__(self, sessions: sessionmaker[Session], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    @contextmanager
    def tx(self) -> Iterator[Tx]:
        with unit_of_work(self.sessions, self.clock) as tx:
            yield tx


def get_work(request: Request) -> Work:
    return Work(request.app.state.sessions, request.app.state.clock)


def get_agent(request: Request) -> Agent | None:
    """The agent, or None when no model is configured (degraded mode, C15)."""
    return cast("Agent | None", request.app.state.agent)


@dataclass(frozen=True)
class Caller:
    user_id: uuid.UUID
    role: UserRole
    session_id: uuid.UUID
    email_verified: bool


def _token_of(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def signed_in(
    request: Request,
    work: Annotated[Work, Depends(get_work)],
    authorization: Annotated[str | None, Header()] = None,
) -> Caller:
    """The logged-in caller, or `401`. Also counts the call against N-29."""
    token = _token_of(authorization)
    if token is None:
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    with work.tx() as tx:
        found = auth.session_user(tx, token)
        if found is None:
            raise ApiError(ErrorCode.UNAUTHENTICATED)
        user, session = found
        caller = Caller(
            user.id, UserRole(user.role), session.id, user.email_verified_at is not None
        )
    limiter = cast(Limiter, request.app.state.calls_per_session)
    wait_s = limiter.wait_s(caller.session_id)
    if wait_s:
        raise ApiError(ErrorCode.RATE_LIMITED, details={"retry_after_s": wait_s})
    return caller


def _only(role: UserRole) -> Callable[[Caller], Caller]:
    def check(caller: Annotated[Caller, Depends(signed_in)]) -> Caller:
        if caller.role is not role:
            raise ApiError(ErrorCode.FORBIDDEN)
        return caller

    return check


SignedIn = Annotated[Caller, Depends(signed_in)]
AsClient = Annotated[Caller, Depends(_only(UserRole.CLIENT))]
AsPharmacist = Annotated[Caller, Depends(_only(UserRole.PHARMACIST))]
AsAdmin = Annotated[Caller, Depends(_only(UserRole.ADMIN))]
DoWork = Annotated[Work, Depends(get_work)]
TheSettings = Annotated[Settings, Depends(get_settings)]


def idempotency_key(
    key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=100)] = None,
) -> str:
    """Every creating tap carries a key, so a double tap creates one thing (docs/06 §1)."""
    if not key or not key.strip():
        raise ApiError(ErrorCode.IDEMPOTENCY_KEY_REQUIRED)
    return key.strip()


IdempotencyKey = Annotated[str, Depends(idempotency_key)]


def caller_address(request: Request, settings: Settings) -> str:
    """The network address a request comes from (R-AU8).

    In AWS every request arrives through CloudFront, which states the visitor's address
    in a header of its own that a visitor can't set. `X-Forwarded-For` is never read.
    """
    return stated_address(request, settings) or (
        request.client.host if request.client else "unknown"
    )


def stated_address(request: Request, settings: Settings) -> str | None:
    """The visitor's address when it is known to be the visitor's own, or None.

    Locally it is the peer's. In AWS it is the one CloudFront states; if that header is
    missing (the distribution's origin request policy was changed, docs/12 §4), every
    request would seem to come from the load balancer, and a limit counted per address
    would count everybody together. So there it is None, and said loudly in the log.
    """
    if settings.app_env != "aws":
        if "cloudfront-viewer-address" in request.headers:
            _say_app_env_is_missing_once()
        return request.client.host if request.client else None
    viewer = request.headers.get("cloudfront-viewer-address", "")
    if viewer:
        return viewer.rsplit(":", 1)[0]
    log.error("visitor_address_not_stated", path=request.url.path)
    return None


# Set once the log has said that CloudFront is in front while APP_ENV is not "aws".
_APP_ENV_MISSING_SAID = threading.Event()


def _say_app_env_is_missing_once() -> None:
    """CloudFront's header arrived, so this API runs behind CloudFront, yet APP_ENV is not
    "aws": every request then seems to come from the load balancer, and the limits per
    address (sign-ups, failed logins) count every visitor together (docs/12 §11). The
    header is still not believed: outside AWS anyone could send it. Said once per process,
    not on every request."""
    if not _APP_ENV_MISSING_SAID.is_set():
        _APP_ENV_MISSING_SAID.set()
        log.error("cloudfront_in_front_but_app_env_is_not_aws", missing_setting="APP_ENV=aws")
