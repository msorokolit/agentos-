"""Top-level GET/PATCH/DELETE /agents/{id} + POST /agents/{id}/run."""

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


def _create_agent(client, ws_id):
    r = client.post(
        f"/api/v1/workspaces/{ws_id}/agents",
        json={"name": "x", "slug": "alpha", "model_alias": "chat-default"},
    )
    return r.json()["id"]


def test_get_agent_top_level(client, make_tenant, make_user, make_workspace, add_member, login_as):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    aid = _create_agent(client, w.id)
    r = client.get(f"/api/v1/agents/{aid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == aid
    assert body["slug"] == "alpha"


def test_patch_agent_top_level_bumps_version(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    aid = _create_agent(client, w.id)
    r = client.patch(f"/api/v1/agents/{aid}", json={"name": "Renamed"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Renamed"
    assert body["version"] >= 2


def test_delete_agent_top_level_requires_admin_or_owner(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    """Builder can't delete; admin can."""

    t = make_tenant()
    builder = make_user(t.id, email="b@x")
    w = make_workspace(t.id, slug="default")
    add_member(w.id, builder.id, role="builder")
    login_as(builder)

    aid = _create_agent(client, w.id)

    r = client.delete(f"/api/v1/agents/{aid}")
    assert r.status_code == 403


def test_run_agent_top_level_proxies_runtime(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    aid = _create_agent(client, w.id)
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
        r = client.post(f"/api/v1/agents/{aid}/run", json={"user_message": "hi"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["final_message"] == "Hello!"
    assert "session_id" in body


def test_top_level_agent_404_unknown(client, make_tenant, make_user, login_as):
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    r = client.get(f"/api/v1/agents/{uuid4()}")
    assert r.status_code == 404


def test_top_level_agent_cross_tenant_404(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    """Bob's agent must 404 when fetched by Alice."""

    from agenticos_shared.models import Agent

    a_t = make_tenant(slug="acme")
    alice = make_user(a_t.id, email="alice@a")
    a_w = make_workspace(a_t.id, slug="alpha")
    add_member(a_w.id, alice.id, role="admin")

    b_t = make_tenant(slug="globex")
    b_w = make_workspace(b_t.id, slug="bravo")
    bob_agent = Agent(
        id=uuid4(),
        workspace_id=b_w.id,
        slug="bobs",
        name="Bobs",
        model_alias="chat-default",
    )
    db.add(bob_agent)
    db.commit()

    login_as(alice)
    for verb_url in [
        ("GET", f"/api/v1/agents/{bob_agent.id}"),
        ("PATCH", f"/api/v1/agents/{bob_agent.id}"),
        ("DELETE", f"/api/v1/agents/{bob_agent.id}"),
        ("POST", f"/api/v1/agents/{bob_agent.id}/run"),
    ]:
        verb, url = verb_url
        if verb == "GET":
            resp = client.get(url)
        elif verb == "PATCH":
            resp = client.patch(url, json={"name": "x"})
        elif verb == "DELETE":
            resp = client.delete(url)
        else:
            resp = client.post(url, json={"user_message": "x"})
        assert resp.status_code == 404, f"{verb} {url} -> {resp.status_code}"
