"""Builds the API application. Run with: uvicorn dawalink.api.main:create_app --factory"""

from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session, sessionmaker

from dawalink.agent.setup import build_agent, build_routing
from dawalink.agent.turn import Agent
from dawalink.api.errors import register_error_handlers
from dawalink.api.health import router as health_router
from dawalink.api.limits import Limiter
from dawalink.api.middleware import (
    OriginCheckMiddleware,
    RequestContextMiddleware,
    UnhandledErrorMiddleware,
)
from dawalink.api.routes import (
    accounts,
    conversations,
    pharmacy,
    pharmacy_stock,
    requests,
    reservations,
    search,
)
from dawalink.config import ConfigError, Settings, load_settings
from dawalink.db.session import make_engine
from dawalink.domain.clock import Clock
from dawalink.domain.numbers import (
    API_CALLS_PER_MINUTE,
    CHAT_MESSAGES_PER_MINUTE,
    LOCATION_UPDATES_PER_HOUR,
    MAX_JSON_BODY_BYTES,
)
from dawalink.observability.logging import configure_logging
from dawalink.services.clock import AppClock
from dawalink.services.inventory import MAX_FILE_BYTES

API_PREFIX = "/api/v1"
CORS_PREFLIGHT_MAX_AGE_S = 2 * 60 * 60  # docs/06 §2.1


def _operation_id(route: APIRoute) -> str:
    """Each endpoint is named after its function, so generated clients read well."""
    return route.name


# How many chat turns may run at once. A turn mostly waits for the model, and each
# conversation runs one at a time, so this is "clients waiting for an answer right now".
CHAT_TURNS_AT_ONCE = 8


def create_app(
    settings: Settings | None = None,
    *,
    agent: Agent | None = None,
    clock: Clock | None = None,
    sessions: sessionmaker[Session] | None = None,
) -> FastAPI:
    """`agent`, `clock` and `sessions` are given by tests (a scripted model, a clock they
    move, a transaction that is undone). Otherwise all three come from the settings."""
    settings = settings or load_settings()
    configure_logging(settings.log_level)
    if settings.app_secret_key is None:
        # Without it no sign-up could be counted and no admin could log in (FX-17).
        raise ConfigError("Missing or invalid settings: APP_SECRET_KEY")
    engine = make_engine(settings.database_url)
    sessions = sessions or sessionmaker(engine, expire_on_commit=False)
    clock = clock or AppClock(engine, demo_mode=settings.demo_mode)
    turn_pool = ThreadPoolExecutor(max_workers=CHAT_TURNS_AT_ONCE, thread_name_prefix="chat-turn")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # A turn that is running finishes and saves its reply before the process ends.
        turn_pool.shutdown(wait=True)
        engine.dispose()

    app = FastAPI(
        title="DawaLink API",
        version="1",
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
        openapi_url=f"{API_PREFIX}/openapi.json",
        # Interactive docs exist only in development (docs/06 API-D13).
        docs_url=f"{API_PREFIX}/docs" if settings.app_env == "local" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.clock = clock
    app.state.turn_pool = turn_pool
    # With no model configured the assistant is off, and everything else works (C15).
    app.state.agent = agent or build_agent(settings, sessions, clock)
    # Road times for the search page. The agent has its own; both read one cache.
    app.state.routing = agent.routing if agent else build_routing(settings)
    app.state.last_point_of_client = {}
    app.state.routing_paused_until = 0.0
    app.state.calls_per_session = Limiter(API_CALLS_PER_MINUTE, 60)
    app.state.chat_per_client = Limiter(CHAT_MESSAGES_PER_MINUTE, 60)
    app.state.locations_per_client = Limiter(LOCATION_UPDATES_PER_HOUR, 3600)

    # The last one added runs first:
    # request context > CORS > the origin check > unhandled errors > the routes.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        OriginCheckMiddleware,
        website_url=settings.website_url,
        max_body_bytes=MAX_JSON_BODY_BYTES,
        # A stock file, and the few hundred bytes the browser wraps around it.
        upload_paths=frozenset({f"{API_PREFIX}/pharmacy/inventory/uploads"}),
        max_upload_bytes=MAX_FILE_BYTES + MAX_JSON_BODY_BYTES,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.website_url],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
        max_age=CORS_PREFLIGHT_MAX_AGE_S,
    )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    app.include_router(health_router, prefix=API_PREFIX)
    for routes in (
        accounts,
        conversations,
        pharmacy,
        pharmacy_stock,
        requests,
        reservations,
        search,
    ):
        app.include_router(routes.router, prefix=API_PREFIX)
    return app
