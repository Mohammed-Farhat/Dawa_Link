# One image for the API, the worker and the one-off commands; only the command changes (docs/12 §6).
# Pinned to an exact image, so every build starts from the same base (docs/12 §6).
ARG PYTHON_IMAGE=python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.1@sha256:cf4eedcaa81655197f625739489effcbe71b61ceb1506f332c3facae5deceded /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# Dependencies first, so this layer is rebuilt only when the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE}
RUN useradd --system --uid 10001 --no-create-home dawalink
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
# Reference data, the catalog rules and, when it was built on this laptop, the catalog file.
COPY data ./data
# APP_ENV is "aws" unless something says otherwise: a task definition that forgets it is
# then still safe, because only in AWS is CloudFront's statement of the visitor's address
# believed (R-AU8) and the interactive API docs left out (A#2). docker-compose.yml sets
# "local" for the laptop.
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 APP_ENV=aws
# The version /health shows: `docker build --build-arg APP_VERSION=<git sha>` (docs/12 §12).
# Last, so a new version rebuilds nothing above it.
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}
USER dawalink
EXPOSE 8000
# --timeout-keep-alive: an idle connection stays open longer than the load balancer keeps
# it (60 s, docs/12 §5), so the load balancer is always the one to close it; the other way
# round it may send a request on a connection being closed, and answer 502 (A#15).
# --timeout-graceful-shutdown: on a stop, open answers get 30 s to finish; then the chat
# turns still running finish and save their reply (up to N-37's 60 s). ECS must give the
# task 120 s for both (docs/12 §6).
CMD ["uvicorn", "dawalink.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--timeout-keep-alive", "75", "--timeout-graceful-shutdown", "30"]
