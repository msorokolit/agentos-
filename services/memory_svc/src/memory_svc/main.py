"""memory-svc FastAPI entrypoint."""

from __future__ import annotations

from agenticos_shared.app import make_app
from agenticos_shared.db import init_engine
from fastapi import FastAPI

from .routes import router
from .settings import get_settings
from .state import init_state


async def _on_startup(_app: FastAPI) -> None:
    s = get_settings()
    init_engine(s.database_url)
    init_state(s)


def create_app() -> FastAPI:
    s = get_settings()
    return make_app(
        service_name="memory-svc",
        settings=s,
        version="0.1.0",
        description="Short-term + long-term agent memory.",
        on_startup=[_on_startup],
        routers=[router],
    )


app = create_app()
