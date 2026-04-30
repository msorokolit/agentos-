"""Per-principal HTTP rate limiting using a Redis token bucket.

Each request consumes 1 token from the bucket
``rl:{principal_id}:{minute}``. We allow up to ``rate_limit_per_minute``
requests per principal per minute. Anonymous requests fall back to a
``rl:ip:{ip}:{minute}`` bucket.

If Redis is unavailable, the middleware silently passes everything through.
This keeps tests / dev mode working with no external state.
"""

from __future__ import annotations

import time
from typing import Any

import redis as redis_lib
from agenticos_shared.errors import AgenticOSError
from agenticos_shared.logging import get_logger
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .auth.session import decode_session

log = get_logger(__name__)


class RateLimitedError(AgenticOSError):
    status = 429
    code = "rate_limited"
    title = "Rate limited"


def _identity(request: Request, *, settings) -> str:
    """Best-effort identity for rate-limit bucketing.

    We pull ``sub`` from the session cookie/JWT without a DB hit, falling
    back to client IP for anonymous endpoints (login, callback).
    """

    cookie = request.cookies.get(settings.session_cookie_name)
    auth = request.headers.get("authorization", "")
    raw = cookie or (auth.split(" ", 1)[1] if auth.lower().startswith("bearer ") else None)
    if raw:
        try:
            payload = decode_session(raw, secret=settings.secret_key)
            return f"u:{payload.user_id}"
        except Exception:
            pass
    if request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"


# Endpoints that should never be rate-limited (health, OpenAPI, the OIDC
# discovery hop). We skip the WS upgrade too; chat-burst control happens
# inside the runtime.
_SKIP_PATH_PREFIXES = (
    "/healthz",
    "/readyz",
    "/version",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/api/v1/chat/",
)


class _RedisBucket:
    """Wrap a sync redis-py client with a tiny INCR+EXPIRE pipeline."""

    def __init__(self, client: Any) -> None:
        self._r = client

    def incr(self, key: str, ttl: int) -> int:
        pipe = self._r.pipeline()
        pipe.incr(key, 1)
        pipe.expire(key, ttl)
        res = pipe.execute()
        return int(res[0])


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that limits requests per principal per minute."""

    def __init__(
        self,
        app,
        *,
        settings,
        bucket: _RedisBucket | None = None,
        per_minute: int | None = None,
    ) -> None:
        super().__init__(app)
        self._settings = settings
        self._bucket = bucket
        self._limit = per_minute or settings.rate_limit_per_minute

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(_SKIP_PATH_PREFIXES):
            return await call_next(request)
        if self._bucket is None or self._limit <= 0:
            return await call_next(request)

        ident = _identity(request, settings=self._settings)
        minute = int(time.time() // 60)
        key = f"rl:{ident}:{minute}"
        try:
            count = self._bucket.incr(key, ttl=70)
        except Exception as exc:
            log.warning("rate_limit_bucket_failed", error=str(exc))
            return await call_next(request)

        if count > self._limit:
            problem = RateLimitedError(
                f"rate limit exceeded ({self._limit}/min for {ident})",
                extras={"retry_after_seconds": 60 - int(time.time() % 60)},
            ).to_problem(instance=str(request.url.path))
            resp = JSONResponse(
                status_code=429,
                content=problem.model_dump(exclude_none=True),
                media_type="application/problem+json",
            )
            resp.headers["Retry-After"] = "60"
            resp.headers["X-RateLimit-Limit"] = str(self._limit)
            resp.headers["X-RateLimit-Remaining"] = "0"
            return resp

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self._limit - count))
        return response


def make_bucket(redis_url: str) -> _RedisBucket | None:
    """Try to construct a bucket; return None if redis is unreachable."""

    try:
        client = redis_lib.from_url(redis_url, decode_responses=True)
        client.ping()
        return _RedisBucket(client)
    except Exception as exc:
        log.warning("redis_unavailable_skipping_rate_limit", error=str(exc))
        return None
