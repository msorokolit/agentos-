"""knowledge-svc FastAPI entrypoint (Phase 0: health only)."""

from __future__ import annotations

from agenticos_shared.app import make_app

from .settings import get_settings


def create_app():  # type: ignore[no-untyped-def]
    settings = get_settings()
    return make_app(
        service_name="knowledge-svc",
        settings=settings,
        version="0.1.0",
        description="Document ingestion, embeddings, and vector search.",
    )


app = create_app()
