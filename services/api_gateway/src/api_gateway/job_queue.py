"""Tiny wrapper around ``arq`` to enqueue background jobs.

Used by the api-gateway to trigger session summarisation when a chat
session ends. We hold a single redis pool for the process and degrade
gracefully when redis is unavailable (the request still succeeds; the
summary just won't be produced).
"""

from __future__ import annotations

from typing import Any

from agenticos_shared.logging import get_logger
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from .settings import Settings

log = get_logger(__name__)

_pool: ArqRedis | None = None


async def init_queue(s: Settings) -> None:
    global _pool
    try:
        _pool = await create_pool(RedisSettings.from_dsn(s.redis_url))
        log.info("arq.connected", url=s.redis_url)
    except Exception as exc:
        log.warning("arq.connect_failed", error=str(exc))
        _pool = None


async def shutdown_queue() -> None:
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass


async def enqueue(name: str, *args: Any, **kwargs: Any) -> str | None:
    """Enqueue a job; returns the job id or None if the queue is unreachable."""

    if _pool is None:
        return None
    try:
        job = await _pool.enqueue_job(name, *args, **kwargs)
    except Exception as exc:
        log.warning("arq.enqueue_failed", job=name, error=str(exc))
        return None
    return job.job_id if job else None
