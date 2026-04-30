"""Tools proxy: RBAC + forwarding + audit."""

from __future__ import annotations

from uuid import uuid4

import respx


def _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="builder@x")
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")
    login_as(u)
    return u, w


def test_list_tools_requires_membership(client, make_tenant, make_user, make_workspace, login_as):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    login_as(u)

    r = client.get(f"/api/v1/workspaces/{w.id}/tools")
    assert r.status_code == 403


def test_create_tool_proxies_and_audits(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    upstream = {
        "id": str(uuid4()),
        "workspace_id": str(w.id),
        "name": "http_get",
        "display_name": "HTTP GET",
        "description": None,
        "kind": "builtin",
        "descriptor": {},
        "scopes": ["safe"],
        "enabled": True,
        "created_at": "2026-04-30T00:00:00Z",
    }
    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://tool-registry:8083/tools").respond(201, json=upstream)
        r = client.post(
            f"/api/v1/workspaces/{w.id}/tools",
            json={
                "name": "http_get",
                "kind": "builtin",
                "descriptor": {"name": "http_get", "parameters": {}},
                "scopes": ["safe"],
            },
        )
    assert r.status_code == 201, r.text

    # workspace_id is injected by the gateway.
    sent = route.calls[0].request.read().decode()
    assert str(w.id) in sent

    from agenticos_shared.models import AuditEventRow

    rows = db.query(AuditEventRow).filter_by(action="tool.create").all()
    assert len(rows) == 1


def test_invoke_tool_audits(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    tool_id = uuid4()
    with respx.mock() as router:
        router.post("http://tool-registry:8083/invoke").respond(
            200,
            json={"ok": True, "result": {"status": 200}, "latency_ms": 10},
        )
        r = client.post(
            f"/api/v1/workspaces/{w.id}/tools/{tool_id}/invoke",
            json={"args": {"url": "https://x"}},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    from agenticos_shared.models import AuditEventRow

    assert db.query(AuditEventRow).filter_by(action="tool.invoke").count() == 1


def test_member_role_cannot_create_tool(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="member")  # member can read but not write
    login_as(u)

    r = client.post(
        f"/api/v1/workspaces/{w.id}/tools",
        json={
            "name": "http_get",
            "kind": "builtin",
            "descriptor": {},
        },
    )
    assert r.status_code == 403
