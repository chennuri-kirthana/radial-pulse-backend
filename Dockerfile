# syntax=docker/dockerfile:1.7
# Radial Pulse API — production image.
# Multi-stage: dependencies are resolved with uv from the lockfile, the runtime
# image has no build tools, runs as a non-root user and has no secrets baked in.

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- build stage
FROM python:${PYTHON_VERSION}-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
# Dependencies first (better layer caching). uv.lock must be committed (`uv lock`).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# -------------------------------------------------------------- runtime stage
FROM python:${PYTHON_VERSION}-slim AS runtime
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.source="https://github.com/<org>/radial-pulse-backend" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.title="radial-pulse-api"
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_VERSION=${GIT_SHA}
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build --chown=app:app /app /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]
# Migrations are NOT run on container start; they run as a separate one-off task
# in the deploy pipeline (see .github/workflows/deploy-*.yml).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*", "--no-server-header"]
