"""Smoke + healthz tests for api-gateway."""

from __future__ import annotations


def test_healthz(client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["service"] == "api-gateway"


def test_readyz(client) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200


def test_openapi_lists_phase1_routes(client) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = set(r.json()["paths"].keys())
    expected = {
        "/api/v1/me",
        "/api/v1/workspaces",
        "/api/v1/workspaces/{workspace_id}",
        "/api/v1/workspaces/{workspace_id}/members",
        "/api/v1/workspaces/{workspace_id}/members/{user_id}",
        "/api/v1/auth/oidc/login",
        "/api/v1/auth/oidc/callback",
        "/api/v1/auth/logout",
    }
    missing = expected - paths
    assert not missing, f"missing routes: {missing}"
