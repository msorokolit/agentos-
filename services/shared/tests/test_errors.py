"""Error → Problem conversions."""

from __future__ import annotations

from agenticos_shared.errors import (
    AgenticOSError,
    ForbiddenError,
    NotFoundError,
    PolicyDeniedError,
    Problem,
    UnauthorizedError,
    ValidationError,
)


def test_default_status_codes() -> None:
    assert NotFoundError().status == 404
    assert ForbiddenError().status == 403
    assert UnauthorizedError().status == 401
    assert ValidationError().status == 422
    assert PolicyDeniedError().status == 403
    assert PolicyDeniedError().code == "policy_denied"


def test_to_problem_includes_extras() -> None:
    err = AgenticOSError(
        "boom", status=503, code="service_unavailable", title="Down", extras={"hint": "retry"}
    )
    p = err.to_problem(instance="/foo")
    assert isinstance(p, Problem)
    assert p.status == 503
    assert p.code == "service_unavailable"
    assert p.title == "Down"
    assert p.detail == "boom"
    assert p.instance == "/foo"
    assert p.extras == {"hint": "retry"}
