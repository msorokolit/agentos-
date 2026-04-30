"""Reusable health-check endpoint mounted on every FastAPI service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI


def make_health_router(*, service_name: str, version: str = "0.1.0") -> APIRouter:
    """Return an APIRouter with /healthz, /readyz, /version."""

    router = APIRouter(tags=["health"])

    @router.get("/healthz", summary="Liveness probe")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "service": service_name}

    @router.get("/readyz", summary="Readiness probe")
    async def readyz() -> dict[str, Any]:
        # Subclasses can extend with deeper checks via dep injection.
        return {"status": "ready", "service": service_name}

    @router.get("/version", summary="Service version")
    async def version_endpoint() -> dict[str, Any]:
        return {"service": service_name, "version": version}

    return router


def attach_health(app: FastAPI, *, service_name: str, version: str = "0.1.0") -> None:
    app.include_router(make_health_router(service_name=service_name, version=version))
