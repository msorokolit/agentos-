"""Tiny arq enqueue helper used by the async upload route.

We keep a single redis pool per process; if redis is unreachable we
simply return ``None`` and the caller falls back to synchronous
ingestion so dev/tests still work without an external worker.
"""

from __future__ import annotations

from typing import Any

from agenticos_shared.logging import get_logger
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

log = get_logger(__name__)

_pool: ArqRedis | None = None


async def init_queue(redis_url: str) -> None:
    global _pool
    try:
        _pool = await create_pool(RedisSettings.from_dsn(redis_url))
        log.info("knowledge.arq.connected", url=redis_url)
    except Exception as exc:
        log.warning("knowledge.arq.connect_failed", error=str(exc))
        _pool = None


async def shutdown_queue() -> None:
    global _pool
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass
        _pool = None


async def enqueue(name: str, *args: Any, **kwargs: Any) -> str | None:
    if _pool is None:
        return None
    try:
        job = await _pool.enqueue_job(name, *args, **kwargs)
    except Exception as exc:
        log.warning("knowledge.arq.enqueue_failed", job=name, error=str(exc))
        return None
    return job.job_id if job else None
