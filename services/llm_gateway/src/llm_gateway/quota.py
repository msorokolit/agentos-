"""Per-workspace token + RPM quota using Redis counters.

We use simple INCR + EXPIRE keys (no Lua). Good enough for in-process
fairness; for hard SLOs swap in a token bucket later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agenticos_shared.errors import AgenticOSError


class QuotaExceededError(AgenticOSError):
    status = 429
    code = "quota_exceeded"
    title = "Quota exceeded"


@dataclass
class QuotaState:
    rpm_count: int
    rpm_limit: int
    tokens_today: int
    tokens_limit: int

    def remaining_tokens(self) -> int:
        return max(0, self.tokens_limit - self.tokens_today)

    def remaining_rpm(self) -> int:
        return max(0, self.rpm_limit - self.rpm_count)


def _today_key(workspace_id: UUID) -> str:
    day = time.strftime("%Y%m%d", time.gmtime())
    return f"quota:tokens:{workspace_id}:{day}"


def _minute_key(workspace_id: UUID) -> str:
    minute = int(time.time() // 60)
    return f"quota:rpm:{workspace_id}:{minute}"


class QuotaService:
    """Wraps a Redis client (sync) for simple INCR/EXPIRE."""

    def __init__(self, redis: Any, *, rpm_limit: int, daily_token_limit: int) -> None:
        self._r = redis
        self._rpm_limit = rpm_limit
        self._tok_limit = daily_token_limit

    def _incr(self, key: str, by: int, ttl: int) -> int:
        """Atomic INCR + first-time EXPIRE (uses sync redis-py pipeline)."""

        pipe = self._r.pipeline()
        pipe.incrby(key, by)
        pipe.expire(key, ttl)
        res = pipe.execute()
        return int(res[0])

    async def check_and_reserve_request(self, workspace_id: UUID | None) -> QuotaState:
        if workspace_id is None or self._rpm_limit <= 0:
            return QuotaState(0, self._rpm_limit, 0, self._tok_limit)

        rpm_key = _minute_key(workspace_id)
        rpm = self._incr(rpm_key, 1, 70)
        tok_key = _today_key(workspace_id)
        # peek tokens
        try:
            cur_raw = self._r.get(tok_key)
        except Exception:
            cur_raw = None
        cur = int(cur_raw or 0)

        if rpm > self._rpm_limit:
            raise QuotaExceededError(f"workspace exceeded {self._rpm_limit} req/min")
        if self._tok_limit > 0 and cur >= self._tok_limit:
            raise QuotaExceededError(f"workspace exhausted daily token budget ({self._tok_limit})")
        return QuotaState(
            rpm_count=rpm,
            rpm_limit=self._rpm_limit,
            tokens_today=cur,
            tokens_limit=self._tok_limit,
        )

    async def add_tokens(self, workspace_id: UUID | None, *, prompt: int, completion: int) -> int:
        if workspace_id is None or self._tok_limit <= 0:
            return 0
        total = max(0, prompt + completion)
        if total == 0:
            return 0
        return self._incr(_today_key(workspace_id), total, 90_000)


# A no-op fallback used in tests / environments without Redis.
class NoopQuotaService(QuotaService):
    def __init__(self) -> None:
        # We intentionally skip super().__init__ — no Redis here.
        self._rpm_limit = 0
        self._tok_limit = 0

    async def check_and_reserve_request(self, workspace_id: UUID | None) -> QuotaState:
        return QuotaState(0, 0, 0, 0)

    async def add_tokens(self, workspace_id: UUID | None, *, prompt: int, completion: int) -> int:
        return 0
