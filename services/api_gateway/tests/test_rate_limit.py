"""Rate limit middleware behaviour."""

from __future__ import annotations


class _FakeBucket:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def incr(self, key: str, ttl: int) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


def test_passthrough_with_no_bucket(client) -> None:
    # No bucket configured (default behaviour in tests) — middleware shouldn't 429.
    for _ in range(50):
        r = client.get("/api/v1/me")
        # /me returns 401 without auth; never 429.
        assert r.status_code in (200, 401)


def test_rate_limit_blocks_when_bucket_exceeded(
    client, app, settings, make_tenant, make_user, login_as
):
    """Install a fake bucket with a tiny limit and ensure we get a 429."""

    from api_gateway.rate_limit import RateLimitMiddleware

    # Replace the rate-limit middleware's bucket + limit on the live app.
    for mw in app.user_middleware:
        if mw.cls is RateLimitMiddleware:
            mw.kwargs["bucket"] = _FakeBucket()
            mw.kwargs["per_minute"] = 3
            break
    else:
        return  # not installed in this app — skip
    # Rebuild middleware stack.
    app.middleware_stack = app.build_middleware_stack()

    t = make_tenant()
    u = make_user(t.id)
    login_as(u)

    statuses = []
    for _ in range(6):
        statuses.append(client.get("/api/v1/me").status_code)
    # First 3 succeed, then 429.
    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]


def test_rate_limit_skips_health(client, app):
    """Health endpoints must never be rate-limited."""

    from api_gateway.rate_limit import RateLimitMiddleware

    for mw in app.user_middleware:
        if mw.cls is RateLimitMiddleware:
            mw.kwargs["bucket"] = _FakeBucket()
            mw.kwargs["per_minute"] = 1
            break
    else:
        return
    app.middleware_stack = app.build_middleware_stack()

    for _ in range(10):
        assert client.get("/healthz").status_code == 200
