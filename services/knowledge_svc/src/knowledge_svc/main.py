"""knowledge-svc FastAPI entrypoint."""

from __future__ import annotations

from agenticos_shared.app import make_app
from agenticos_shared.db import init_engine
from fastapi import FastAPI

from .queue import init_queue, shutdown_queue
from .routes import router
from .settings import get_settings


async def _on_startup(_app: FastAPI) -> None:
    s = get_settings()
    init_engine(s.database_url)
    await init_queue(s.redis_url)


async def _on_shutdown(_app: FastAPI) -> None:
    await shutdown_queue()


def create_app() -> FastAPI:
    s = get_settings()
    return make_app(
        service_name="knowledge-svc",
        settings=s,
        version="0.1.0",
        description="Document ingestion, embeddings, and hybrid search.",
        on_startup=[_on_startup],
        on_shutdown=[_on_shutdown],
        routers=[router],
    )


app = create_app()
