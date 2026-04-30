"""Process-wide state for memory-svc."""

from __future__ import annotations

import redis
from agenticos_shared.logging import get_logger

from .settings import Settings
from .short_term import ShortTermStore

log = get_logger(__name__)

_stm: ShortTermStore | None = None


def init_state(s: Settings) -> None:
    global _stm
    try:
        client = redis.from_url(s.redis_url, decode_responses=True)
        client.ping()
        _stm = ShortTermStore(client, default_ttl=s.short_term_default_ttl)
        log.info("redis.connected", url=s.redis_url)
    except Exception as exc:
        log.warning("redis.unavailable_using_inmemory_stm", error=str(exc))
        _stm = ShortTermStore(None, default_ttl=s.short_term_default_ttl)


def get_short_term() -> ShortTermStore:
    if _stm is None:
        return ShortTermStore(None)
    return _stm
