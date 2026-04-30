"""POST/DELETE /agents/{id}/tools/{tool_id} bind+unbind routes."""

from __future__ import annotations

from uuid import uuid4

from agenticos_shared.models import ToolBinding, ToolRow


def _seed_tool(db, workspace_id) -> str:
    t = ToolRow(
        id=uuid4(),
        workspace_id=workspace_id,
        name=f"t-{uuid4().hex[:6]}",
        kind="builtin",
        descriptor={},
        scopes=[],
        enabled=True,
    )
    db.add(t)
    db.commit()
    return str(t.id)


def _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="admin@x", is_superuser=True)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="admin")
    login_as(u)
    return u, w


def _create_empty_agent(client, ws_id):
    return client.post(
        f"/api/v1/workspaces/{ws_id}/agents",
        json={"name": "x", "slug": "alpha", "model_alias": "chat-default"},
    ).json()["id"]


def test_bind_then_unbind(client, db, make_tenant, make_user, make_workspace, add_member, login_as):
    from uuid import UUID

    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    aid = _create_empty_agent(client, w.id)
    tid = _seed_tool(db, w.id)
    tid_uuid = UUID(tid)

    r = client.post(f"/api/v1/workspaces/{w.id}/agents/{aid}/tools/{tid}")
    assert r.status_code == 201, r.text
    assert tid in r.json()["tool_ids"]
    # Join table reflects the bind.
    bindings = db.query(ToolBinding).all()
    assert any(b.tool_id == tid_uuid for b in bindings)

    # Idempotent re-bind.
    r2 = client.post(f"/api/v1/workspaces/{w.id}/agents/{aid}/tools/{tid}")
    assert r2.status_code == 201
    assert r2.json()["tool_ids"].count(tid) == 1

    # Unbind.
    r3 = client.delete(f"/api/v1/workspaces/{w.id}/agents/{aid}/tools/{tid}")
    assert r3.status_code == 204
    assert db.query(ToolBinding).filter(ToolBinding.tool_id == tid_uuid).count() == 0


def test_unbind_unknown_404(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    aid = _create_empty_agent(client, w.id)
    tid = _seed_tool(db, w.id)
    r = client.delete(f"/api/v1/workspaces/{w.id}/agents/{aid}/tools/{tid}")
    assert r.status_code == 404


def test_bind_creates_audit(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    aid = _create_empty_agent(client, w.id)
    tid = _seed_tool(db, w.id)
    client.post(f"/api/v1/workspaces/{w.id}/agents/{aid}/tools/{tid}")
    audit = client.get(f"/api/v1/workspaces/{w.id}/audit").json()
    actions = {row["action"] for row in audit}
    assert "agent.tool.bind" in actions
