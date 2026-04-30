"""llm-gateway FastAPI entrypoint."""

from __future__ import annotations

from agenticos_shared.app import make_app
from agenticos_shared.db import init_engine
from fastapi import FastAPI

from . import registry
from .routes.models_admin import router as admin_router
from .routes.v1 import router as v1_router
from .settings import get_settings
from .state import init_state


async def _on_startup(_app: FastAPI) -> None:
    s = get_settings()
    init_engine(s.database_url)
    init_state(
        s.redis_url,
        rpm_limit=s.rpm_per_workspace,
        daily_token_limit=s.daily_token_budget_per_workspace,
    )
    try:
        await registry.reload_cache()
    except Exception:
        pass


def create_app() -> FastAPI:
    s = get_settings()
    app = make_app(
        service_name="llm-gateway",
        settings=s,
        version="0.1.0",
        description="OpenAI-compatible router across local LLM providers.",
        on_startup=[_on_startup],
        routers=[admin_router, v1_router],
    )
    return app


app = create_app()
