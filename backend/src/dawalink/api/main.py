"""Builds the API application. Run with: uvicorn dawalink.api.main:create_app --factory"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from dawalink.api.errors import register_error_handlers
from dawalink.api.health import router as health_router
from dawalink.api.middleware import RequestContextMiddleware, UnhandledErrorMiddleware
from dawalink.config import Settings, load_settings
from dawalink.db.session import make_engine
from dawalink.observability.logging import configure_logging

API_PREFIX = "/api/v1"
CORS_PREFLIGHT_MAX_AGE_S = 2 * 60 * 60  # docs/06 §2.1


def _operation_id(route: APIRoute) -> str:
    """Each endpoint is named after its function, so generated clients read well."""
    return route.name


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
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

    # The last one added runs first: request context > CORS > unhandled errors > the routes.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.website_url],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
        max_age=CORS_PREFLIGHT_MAX_AGE_S,
    )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    app.include_router(health_router, prefix=API_PREFIX)
    return app
