"""Reusable FastAPI app factory.

Every AgenticOS Python service builds its FastAPI ``app`` via
:func:`make_app`. This guarantees:

- consistent service metadata
- structured logging configured at startup
- OTel initialised
- /healthz, /readyz, /version mounted
- problem+json error responses
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .errors import AgenticOSError, Problem
from .healthz import attach_health
from .logging import configure_logging, get_logger
from .otel import init_otel
from .settings import BaseServiceSettings


def _problem_response(problem: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


def make_app(
    *,
    service_name: str,
    settings: BaseServiceSettings,
    version: str = "0.1.0",
    routers: Sequence[Any] = (),
    on_startup: Sequence[Callable[[FastAPI], Any]] = (),
    on_shutdown: Sequence[Callable[[FastAPI], Any]] = (),
    description: str = "",
) -> FastAPI:
    """Build a fully wired FastAPI app for a service."""

    configure_logging(level=settings.log_level, json=settings.is_production)
    init_otel(
        service_name=service_name,
        endpoint=settings.otel_endpoint,
        namespace=settings.otel_service_namespace,
    )
    log = get_logger(service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("service.starting", service=service_name, env=settings.env)
        for cb in on_startup:
            res = cb(app)
            if hasattr(res, "__await__"):
                await res  # type: ignore[func-returns-value]
        try:
            yield
        finally:
            for cb in on_shutdown:
                res = cb(app)
                if hasattr(res, "__await__"):
                    await res  # type: ignore[func-returns-value]
            log.info("service.stopped", service=service_name)

    app = FastAPI(
        title=service_name,
        version=version,
        description=description or f"AgenticOS {service_name} service",
        lifespan=lifespan,
    )

    attach_health(app, service_name=service_name, version=version)
    for router in routers:
        app.include_router(router)

    @app.exception_handler(AgenticOSError)
    async def _agenticos_error_handler(request: Request, exc: AgenticOSError) -> JSONResponse:
        problem = exc.to_problem(instance=str(request.url.path))
        log.warning(
            "request.error",
            path=request.url.path,
            code=exc.code,
            status=exc.status,
            detail=exc.detail,
        )
        return _problem_response(problem)

    return app
