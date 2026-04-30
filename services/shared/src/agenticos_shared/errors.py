"""RFC-7807 problem+json error helpers.

Use these in FastAPI services to return consistent, machine-friendly errors.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Problem(BaseModel):
    """RFC-7807 problem details object."""

    type: str = Field(default="about:blank")
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str | None = None
    extras: dict[str, Any] | None = None


class AgenticOSError(Exception):
    """Base exception for all AgenticOS-thrown errors."""

    status: int = 500
    code: str = "internal_error"
    title: str = "Internal Server Error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        status: int | None = None,
        code: str | None = None,
        title: str | None = None,
        extras: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code
        if title is not None:
            self.title = title
        self.detail = detail
        self.extras = extras

    def to_problem(self, instance: str | None = None) -> Problem:
        return Problem(
            title=self.title,
            status=self.status,
            detail=self.detail,
            instance=instance,
            code=self.code,
            extras=self.extras,
        )


class NotFoundError(AgenticOSError):
    status = 404
    code = "not_found"
    title = "Not Found"


class ForbiddenError(AgenticOSError):
    status = 403
    code = "forbidden"
    title = "Forbidden"


class UnauthorizedError(AgenticOSError):
    status = 401
    code = "unauthorized"
    title = "Unauthorized"


class ValidationError(AgenticOSError):
    status = 422
    code = "validation_error"
    title = "Validation Error"


class ConflictError(AgenticOSError):
    status = 409
    code = "conflict"
    title = "Conflict"


class PolicyDeniedError(ForbiddenError):
    code = "policy_denied"
    title = "Policy Denied"
