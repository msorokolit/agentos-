"""api-gateway FastAPI entrypoint.

Phase 1: OIDC + RBAC + workspaces + members + audit.
"""

from __future__ import annotations

from agenticos_shared.app import make_app
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .audit_bus import init_audit, shutdown_audit
from .db import init_db
from .error_handlers import install_exception_handlers
from .rate_limit import RateLimitMiddleware, make_bucket
from .routes.admin_models import router as admin_models_router
from .routes.agents import router as agents_router
from .routes.api_keys import router as api_keys_router
from .routes.audit import router as audit_router
from .routes.auth import router as auth_router
from .routes.chat import router as chat_router
from .routes.knowledge import router as knowledge_router
from .routes.me import router as me_router
from .routes.tools import router as tools_router
from .routes.workspaces import router as workspaces_router
from .security_headers import SecurityHeadersMiddleware
from .settings import get_settings


async def _on_startup(_app: FastAPI) -> None:
    settings = get_settings()
    init_db()
    await init_audit(settings.nats_url)


async def _on_shutdown(_app: FastAPI) -> None:
    await shutdown_audit()


def create_app() -> FastAPI:
    settings = get_settings()
    app = make_app(
        service_name="api-gateway",
        settings=settings,
        version="0.1.0",
        description="Public REST + WebSocket gateway for AgenticOS.",
        on_startup=[_on_startup],
        on_shutdown=[_on_shutdown],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security headers on every response.
    app.add_middleware(SecurityHeadersMiddleware)

    # Rate-limit (skipped automatically when Redis is unreachable).
    bucket = make_bucket(settings.redis_url)
    app.add_middleware(RateLimitMiddleware, settings=settings, bucket=bucket)

    install_exception_handlers(app)

    api = APIRouter(prefix=settings.api_prefix)
    api.include_router(auth_router)
    api.include_router(me_router)
    api.include_router(workspaces_router)
    api.include_router(admin_models_router)
    api.include_router(knowledge_router)
    api.include_router(tools_router)
    api.include_router(agents_router)
    api.include_router(chat_router)
    api.include_router(audit_router)
    api.include_router(api_keys_router)
    app.include_router(api)
    return app


app = create_app()
