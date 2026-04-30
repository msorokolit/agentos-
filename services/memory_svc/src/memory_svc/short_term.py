"""Short-term memory: the recent message buffer kept in Redis.

Implementation: a per-session list ``stm:{workspace_id}:{session_id}`` of
JSON-encoded ``ShortTermItem``s, capped at ``max_messages`` via LTRIM and
expiring after the configured TTL (default 1h).

If Redis is unavailable, all calls are best-effort no-ops; the route returns
empty lists. This keeps tests / dev mode running without redis.
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import UUID

from agenticos_shared.logging import get_logger

log = get_logger(__name__)


def _key(workspace_id: UUID, session_id: UUID) -> str:
    return f"stm:{workspace_id}:{session_id}"


class ShortTermStore:
    """Wraps a sync redis-py client; degrades gracefully when redis is missing."""

    def __init__(self, redis: Any | None, *, default_ttl: int = 3600) -> None:
        self._r = redis
        self._ttl = default_ttl

    def append(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
        role: str,
        content: str,
        max_messages: int = 40,
        ttl_seconds: int | None = None,
    ) -> int:
        if self._r is None:
            return 0
        key = _key(workspace_id, session_id)
        item = json.dumps({"role": role, "content": content, "ts": time.time()})
        try:
            pipe = self._r.pipeline()
            pipe.rpush(key, item)
            pipe.ltrim(key, -max_messages, -1)
            pipe.expire(key, int(ttl_seconds or self._ttl))
            pipe.llen(key)
            res = pipe.execute()
            return int(res[-1] or 0)
        except Exception as exc:
            log.warning("stm_append_failed", error=str(exc))
            return 0

    def get(
        self, *, workspace_id: UUID, session_id: UUID, limit: int = 200
    ) -> list[dict[str, Any]]:
        if self._r is None:
            return []
        key = _key(workspace_id, session_id)
        try:
            raw = self._r.lrange(key, -limit, -1) or []
        except Exception as exc:
            log.warning("stm_get_failed", error=str(exc))
            return []
        out: list[dict[str, Any]] = []
        for r in raw:
            try:
                if isinstance(r, bytes):
                    r = r.decode("utf-8", "replace")
                out.append(json.loads(r))
            except Exception:
                continue
        return out

    def clear(self, *, workspace_id: UUID, session_id: UUID) -> None:
        if self._r is None:
            return
        try:
            self._r.delete(_key(workspace_id, session_id))
        except Exception as exc:
            log.warning("stm_clear_failed", error=str(exc))
