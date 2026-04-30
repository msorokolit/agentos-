# Generic Dockerfile for any AgenticOS Python service.
#
# Build with:
#   docker build -f services/Dockerfile \
#       --build-arg SERVICE_PKG=api_gateway \
#       --build-arg SERVICE_MODULE=api_gateway.main:app \
#       -t agenticos/api-gateway .
#
# (docker-compose.yml does this for every service.)

# ---------- builder ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# System deps for psycopg / cryptography / etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only what we need.
COPY services/shared /build/shared
ARG SERVICE_PKG
COPY services/${SERVICE_PKG} /build/service

RUN pip install --upgrade pip wheel \
 && pip install /build/shared \
 && pip install /build/service

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Runtime libs only.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd  --system --gid app --home /app --shell /usr/sbin/nologin app

# Copy installed python packages from builder.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy migrations (used by api-gateway when running `alembic upgrade head`).
COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations
COPY scripts /app/scripts

WORKDIR /app
USER app

ARG SERVICE_MODULE=api_gateway.main:app
ENV SERVICE_MODULE=${SERVICE_MODULE}
ENV PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

# Default: run uvicorn. Override `command:` in compose for the worker.
CMD ["sh", "-c", "exec uvicorn ${SERVICE_MODULE} --host 0.0.0.0 --port ${PORT}"]
