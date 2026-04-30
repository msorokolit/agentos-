"""HTTPException + RequestValidationError → problem+json mapping."""

from __future__ import annotations


def test_validation_error_uses_problem_json(client, make_tenant, make_user, login_as):
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    # Missing required ``slug`` field.
    r = client.post("/api/v1/workspaces", json={"name": "x"})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 422
    assert body["code"] == "validation_error"
    assert body["title"] == "Validation Error"
    # Detail array under extras.errors with loc / msg / type.
    errs = body["extras"]["errors"]
    assert any(
        e["msg"].lower().startswith("field required")
        or "missing" in e["msg"].lower()
        or "required" in e["msg"].lower()
        for e in errs
    )


def test_http_exception_uses_problem_json(client, make_tenant, make_user, login_as):
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    # POST /api/v1/auth/oidc/callback without code/state → 400 HTTPException.
    r = client.get("/api/v1/auth/oidc/callback")
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 400
    assert body["title"] == "Bad Request"
    assert body["code"] == "http_400"
