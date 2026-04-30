"""api-gateway FastAPI entrypoint.

Phase 0: only health endpoints. Phase 1 adds OIDC, workspaces, RBAC.
"""

from __future__ import annotations

from agenticos_shared.app import make_app
from fastapi.middleware.cors import CORSMiddleware

from .settings import get_settings


def create_app():  # type: ignore[no-untyped-def]
    settings = get_settings()
    app = make_app(
        service_name="api-gateway",
        settings=settings,
        version="0.1.0",
        description="Public REST + WebSocket gateway for AgenticOS.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


app = create_app()
