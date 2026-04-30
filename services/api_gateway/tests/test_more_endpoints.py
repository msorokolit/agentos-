"""POST /agents/{id}/versions, POST /sessions, GET /admin/health."""

from __future__ import annotations

from uuid import uuid4

import respx


def _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="admin@x", is_superuser=True)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="admin")
    login_as(u)
    return u, w


# ---------------------------------------------------------------------------
# Agent publish
# ---------------------------------------------------------------------------
def test_publish_creates_immutable_snapshot(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)

    r = client.post(
        f"/api/v1/workspaces/{w.id}/agents",
        json={"name": "A", "slug": "a", "model_alias": "chat-default"},
    )
    aid = r.json()["id"]

    r = client.post(
        f"/api/v1/workspaces/{w.id}/agents/{aid}/versions",
        json={"notes": "first prod release"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"] == 2  # auto v1 from create + explicit publish bumps to v2
    assert body["snapshot"].get("notes") == "first prod release"

    versions = client.get(f"/api/v1/workspaces/{w.id}/agents/{aid}/versions").json()
    versions_seen = [v["version"] for v in versions]
    assert versions_seen == [2, 1]


# ---------------------------------------------------------------------------
# Top-level POST /sessions
# ---------------------------------------------------------------------------
def test_top_level_sessions_resolves_workspace(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    r = client.post(
        f"/api/v1/workspaces/{w.id}/agents",
        json={"name": "x", "slug": "alpha", "model_alias": "chat-default"},
    )
    aid = r.json()["id"]

    r = client.post("/api/v1/sessions", json={"agent_id": aid, "title": "ad-hoc"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["agent_id"] == aid
    assert body["workspace_id"] == str(w.id)
    assert body["title"] == "ad-hoc"


def test_top_level_sessions_404_for_unknown_agent(client, make_tenant, make_user, login_as):
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    r = client.post("/api/v1/sessions", json={"agent_id": str(uuid4())})
    assert r.status_code == 404


def test_top_level_sessions_validation_error_when_missing_agent_id(
    client, make_tenant, make_user, login_as
):
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    r = client.post("/api/v1/sessions", json={})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Aggregate health
# ---------------------------------------------------------------------------
def test_admin_health_aggregates_downstream(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    with respx.mock(assert_all_called=False) as router:
        for host in (
            "http://llm-gateway:8081/healthz",
            "http://agent-runtime:8082/healthz",
            "http://tool-registry:8083/healthz",
            "http://knowledge-svc:8084/healthz",
        ):
            router.get(host).respond(200, json={"status": "ok"})
        r = client.get("/api/v1/admin/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    seen = {s["name"] for s in body["services"]}
    assert seen >= {"llm-gateway", "agent-runtime", "tool-registry", "knowledge-svc"}


def test_admin_health_marks_failing_service(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    with respx.mock(assert_all_called=False) as router:
        router.get("http://llm-gateway:8081/healthz").respond(200, json={"status": "ok"})
        router.get("http://agent-runtime:8082/healthz").respond(503, text="bad")
        router.get("http://tool-registry:8083/healthz").respond(200, json={"status": "ok"})
        router.get("http://knowledge-svc:8084/healthz").respond(200, json={"status": "ok"})
        r = client.get("/api/v1/admin/health")
    body = r.json()
    assert body["ok"] is False
    bad = next(s for s in body["services"] if s["name"] == "agent-runtime")
    assert bad["ok"] is False


def test_admin_health_requires_admin(client, make_tenant, make_user, login_as):
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    r = client.get("/api/v1/admin/health")
    assert r.status_code == 403
