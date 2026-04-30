"""Agents CRUD + run proxy through api-gateway."""

from __future__ import annotations

import respx


def _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="builder@x")
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")
    login_as(u)
    return u, w


def test_list_agents_requires_membership(client, make_tenant, make_user, make_workspace, login_as):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    login_as(u)
    r = client.get(f"/api/v1/workspaces/{w.id}/agents")
    assert r.status_code == 403


def test_create_agent_then_list(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    r = client.post(
        f"/api/v1/workspaces/{w.id}/agents",
        json={
            "name": "Helper",
            "slug": "helper",
            "system_prompt": "you are helpful",
            "model_alias": "chat-default",
            "tool_ids": [],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == "helper"

    r2 = client.get(f"/api/v1/workspaces/{w.id}/agents")
    assert r2.status_code == 200
    assert any(a["slug"] == "helper" for a in r2.json())

    from agenticos_shared.models import AuditEventRow

    assert db.query(AuditEventRow).filter_by(action="agent.create").count() == 1


def test_create_agent_duplicate_slug_409(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    body = {"name": "x", "slug": "dup", "model_alias": "chat-default"}
    assert client.post(f"/api/v1/workspaces/{w.id}/agents", json=body).status_code == 201
    r = client.post(f"/api/v1/workspaces/{w.id}/agents", json=body)
    assert r.status_code == 409


def test_run_agent_proxies_to_runtime(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    r = client.post(
        f"/api/v1/workspaces/{w.id}/agents",
        json={"name": "x", "slug": "alpha", "model_alias": "chat-default"},
    )
    agent_id = r.json()["id"]

    upstream = {
        "final_message": "Hello!",
        "tool_calls": [],
        "tool_results": [],
        "citations": [],
        "iterations": 1,
        "tokens_in": 5,
        "tokens_out": 1,
        "error": None,
    }
    with respx.mock(assert_all_called=True) as router:
        router.post("http://agent-runtime:8082/run").respond(200, json=upstream)
        r2 = client.post(
            f"/api/v1/workspaces/{w.id}/agents/{agent_id}/run",
            json={"user_message": "hi"},
        )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["final_message"] == "Hello!"
    assert "session_id" in body

    from agenticos_shared.models import AuditEventRow

    assert db.query(AuditEventRow).filter_by(action="agent.run").count() == 1


def test_session_messages_after_run(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    r = client.post(
        f"/api/v1/workspaces/{w.id}/agents",
        json={"name": "x", "slug": "alpha", "model_alias": "chat-default"},
    )
    agent_id = r.json()["id"]

    s = client.post(
        f"/api/v1/workspaces/{w.id}/agents/{agent_id}/sessions",
        json={"title": "Hi"},
    ).json()
    session_id = s["id"]

    # No messages yet
    r2 = client.get(f"/api/v1/workspaces/{w.id}/sessions/{session_id}/messages")
    assert r2.status_code == 200
    assert r2.json() == []
