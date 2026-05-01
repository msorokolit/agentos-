"""Worker entrypoint.

Two run modes:

* ``arq worker.main.WorkerSettings`` — process jobs from Redis.
* ``uvicorn worker.main:app``       — exposes /healthz only (for compose).

The two modes can run in the same container (we start arq via the worker
service and uvicorn via a separate container) or be combined in dev.
"""

from __future__ import annotations

from typing import ClassVar

from agenticos_shared.app import make_app
from agenticos_shared.db import init_engine
from arq.connections import RedisSettings

from .jobs.ingest_document import ingest_document
from .jobs.ping import ping
from .jobs.summarize_session import summarize_session
from .settings import get_settings


def _redis_settings() -> RedisSettings:
    s = get_settings()
    # arq parses redis://host:port/db; we extract via RedisSettings.from_dsn
    return RedisSettings.from_dsn(s.redis_url)


async def _on_startup(_ctx: dict) -> None:
    s = get_settings()
    init_engine(s.database_url)


class WorkerSettings:
    """arq WorkerSettings — discovered by ``arq`` CLI."""

    redis_settings: ClassVar[RedisSettings] = _redis_settings()
    functions: ClassVar[list] = [ping, summarize_session, ingest_document]
    max_jobs: ClassVar[int] = 4
    job_timeout: ClassVar[int] = 300
    on_startup = _on_startup


def create_app():  # type: ignore[no-untyped-def]
    settings = get_settings()
    return make_app(
        service_name="worker",
        settings=settings,
        version="0.1.0",
        description="Background worker status endpoints.",
    )


app = create_app()
