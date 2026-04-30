"""Map FastAPI's standard exceptions onto RFC-7807 ``problem+json``.

The shared app factory already handles :class:`AgenticOSError`; this module
adds handlers for ``HTTPException`` and ``RequestValidationError`` so the
shape is consistent across error sources.
"""

from __future__ import annotations

from typing import Any

from agenticos_shared.errors import Problem
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request


def _problem_response(p: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=p.status,
        content=p.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


def _http_status_title(status: int) -> str:
    titles: dict[int, str] = {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        409: "Conflict",
        413: "Payload Too Large",
        415: "Unsupported Media Type",
        422: "Unprocessable Entity",
        429: "Too Many Requests",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
    }
    return titles.get(status, "Error")


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else None
    extras: dict[str, Any] | None = None
    if not isinstance(exc.detail, str) and exc.detail is not None:
        extras = {"detail": exc.detail}
    p = Problem(
        title=_http_status_title(exc.status_code),
        status=exc.status_code,
        detail=detail,
        instance=str(request.url.path),
        code=f"http_{exc.status_code}",
        extras=extras,
    )
    return _problem_response(p)


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = []
    for e in exc.errors():
        # Drop pydantic's internal `ctx` (often non-serialisable).
        errors.append(
            {
                "loc": list(e.get("loc", [])),
                "msg": e.get("msg"),
                "type": e.get("type"),
            }
        )
    p = Problem(
        title="Validation Error",
        status=422,
        code="validation_error",
        detail="request validation failed",
        instance=str(request.url.path),
        extras={"errors": errors},
    )
    return _problem_response(p)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
