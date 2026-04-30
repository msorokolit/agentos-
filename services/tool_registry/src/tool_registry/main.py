"""tool-registry FastAPI entrypoint."""

from __future__ import annotations

from agenticos_shared.app import make_app
from agenticos_shared.db import init_engine
from fastapi import FastAPI

from .routes import router
from .settings import get_settings


async def _on_startup(_app: FastAPI) -> None:
    s = get_settings()
    init_engine(s.database_url)


def create_app() -> FastAPI:
    s = get_settings()
    return make_app(
        service_name="tool-registry",
        settings=s,
        version="0.1.0",
        description="Tool registry: built-ins + HTTP/OpenAPI/MCP plugins.",
        on_startup=[_on_startup],
        routers=[router],
    )


app = create_app()
