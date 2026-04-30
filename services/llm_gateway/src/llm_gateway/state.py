"""Process-wide state for llm-gateway (Redis client, quota service)."""

from __future__ import annotations

import redis
from agenticos_shared.logging import get_logger

from .quota import NoopQuotaService, QuotaService

log = get_logger(__name__)

_quota: QuotaService | None = None


def init_state(redis_url: str, *, rpm_limit: int, daily_token_limit: int) -> None:
    global _quota
    try:
        client = redis.from_url(redis_url, decode_responses=True)
        client.ping()
        _quota = QuotaService(client, rpm_limit=rpm_limit, daily_token_limit=daily_token_limit)
        log.info("redis.connected", url=redis_url)
    except Exception as exc:
        log.warning("redis.unavailable_using_noop_quota", error=str(exc))
        _quota = NoopQuotaService()


def get_quota() -> QuotaService:
    if _quota is None:
        return NoopQuotaService()
    return _quota
