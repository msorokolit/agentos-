"""Agent tool_ids stay in sync with the tool_binding join table, and
deleting a tool prunes both the join table and dangling JSON entries."""

from __future__ import annotations

from uuid import UUID, uuid4

import respx
from agenticos_shared.models import ToolBinding, ToolRow


def _seed_tools(db, workspace_id, n: int) -> list[UUID]:
    """Create real ``tool`` rows so tool_binding FKs are satisfied."""

    out: list[UUID] = []
    for i in range(n):
        t = ToolRow(
            id=uuid4(),
            workspace_id=workspace_id,
            name=f"t{i}-{uuid4().hex[:6]}",
            kind="builtin",
            descriptor={},
            scopes=[],
            enabled=True,
        )
        db.add(t)
        out.append(t.id)
    db.commit()
    return out


def _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="admin@x", is_superuser=True)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="admin")
    login_as(u)
    return u, w


def _create_agent_with_tools(client, ws_id, tool_ids):
    return client.post(
        f"/api/v1/workspaces/{ws_id}/agents",
        json={
            "name": "x",
            "slug": "alpha",
            "model_alias": "chat-default",
            "tool_ids": [str(t) for t in tool_ids],
        },
    )


def test_create_writes_bindings(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    tool_ids = _seed_tools(db, w.id, 2)

    r = _create_agent_with_tools(client, w.id, tool_ids)
    assert r.status_code == 201, r.text
    rows = db.query(ToolBinding).all()
    assert {b.tool_id for b in rows} == set(tool_ids)


def test_update_resyncs_bindings(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    a, b, c = _seed_tools(db, w.id, 3)
    r = _create_agent_with_tools(client, w.id, [a, b])
    aid = r.json()["id"]

    r = client.patch(
        f"/api/v1/workspaces/{w.id}/agents/{aid}",
        json={"tool_ids": [str(b), str(c)]},
    )
    assert r.status_code == 200, r.text
    rows = db.query(ToolBinding).all()
    assert {row.tool_id for row in rows} == {b, c}


def test_tool_delete_prunes_dangling_json_ids(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    a, b = _seed_tools(db, w.id, 2)
    r = _create_agent_with_tools(client, w.id, [a, b])
    aid = r.json()["id"]

    # Delete tool ``a`` via the tool-registry proxy.
    with respx.mock(assert_all_called=True) as router:
        router.delete(f"http://tool-registry:8083/tools/{a}").respond(204)
        r = client.delete(f"/api/v1/workspaces/{w.id}/tools/{a}")
    assert r.status_code == 204

    # The agent's JSON list no longer contains the deleted tool_id.
    after = client.get(f"/api/v1/workspaces/{w.id}/agents").json()
    agent = next(x for x in after if x["id"] == aid)
    assert str(a) not in agent["tool_ids"]
    assert str(b) in agent["tool_ids"]

    # And the audit row records which agents were pruned.
    audit = client.get(f"/api/v1/workspaces/{w.id}/audit").json()
    delete_events = [e for e in audit if e["action"] == "tool.delete"]
    assert delete_events
    assert aid in delete_events[0]["payload"]["pruned_agents"]
