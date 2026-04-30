"""Admin /admin/models proxy: requires admin role, forwards to llm-gateway."""

from __future__ import annotations

import respx


def _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="admin@x", is_superuser=True)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="admin")
    login_as(u)
    return u


def test_admin_models_requires_login(client) -> None:
    r = client.get("/api/v1/admin/models")
    assert r.status_code == 401


def test_admin_models_requires_admin_role(
    client, make_tenant, make_user, make_workspace, add_member, login_as
) -> None:
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="member")  # not admin
    login_as(u)

    r = client.get("/api/v1/admin/models")
    assert r.status_code == 403


def test_admin_models_lists_via_proxy(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    upstream = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "alias": "chat-default",
            "provider": "ollama",
            "endpoint": "http://ollama:11434",
            "model_name": "qwen",
            "kind": "chat",
            "capabilities": {},
            "default_params": {},
            "enabled": True,
        }
    ]
    with respx.mock(assert_all_called=True) as router:
        router.get("http://llm-gateway:8081/admin/models").respond(json=upstream)
        r = client.get("/api/v1/admin/models")
    assert r.status_code == 200
    assert r.json() == upstream


def test_admin_models_create_emits_audit(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    upstream = {
        "id": "00000000-0000-0000-0000-000000000001",
        "alias": "chat-default",
        "provider": "ollama",
        "endpoint": "http://ollama:11434",
        "model_name": "qwen",
        "kind": "chat",
        "capabilities": {},
        "default_params": {},
        "enabled": True,
    }
    body = {
        "alias": "chat-default",
        "provider": "ollama",
        "endpoint": "http://ollama:11434",
        "model_name": "qwen",
    }
    with respx.mock() as router:
        router.post("http://llm-gateway:8081/admin/models").respond(201, json=upstream)
        r = client.post("/api/v1/admin/models", json=body)
    assert r.status_code == 201
    assert r.json()["alias"] == "chat-default"

    from agenticos_shared.models import AuditEventRow

    rows = db.query(AuditEventRow).filter_by(action="model.create").all()
    assert len(rows) == 1
    assert rows[0].resource_id == "00000000-0000-0000-0000-000000000001"


def test_admin_models_proxies_error(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    with respx.mock() as router:
        router.post("http://llm-gateway:8081/admin/models").respond(
            409,
            json={
                "type": "about:blank",
                "title": "Conflict",
                "status": 409,
                "code": "conflict",
                "detail": "alias already exists",
            },
        )
        r = client.post(
            "/api/v1/admin/models",
            json={
                "alias": "chat-default",
                "provider": "ollama",
                "endpoint": "http://x",
                "model_name": "y",
            },
        )
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"
