"""Agent updates create immutable agent_version snapshots."""

from __future__ import annotations


def _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="b@x")
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")
    login_as(u)
    return u, w


def test_create_then_update_creates_two_versions(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)

    r = client.post(
        f"/api/v1/workspaces/{w.id}/agents",
        json={"name": "Alpha", "slug": "alpha", "model_alias": "chat-default"},
    )
    assert r.status_code == 201
    agent_id = r.json()["id"]

    r2 = client.patch(
        f"/api/v1/workspaces/{w.id}/agents/{agent_id}",
        json={"name": "Alpha v2", "system_prompt": "be brief"},
    )
    assert r2.status_code == 200
    assert r2.json()["version"] == 2

    versions = client.get(f"/api/v1/workspaces/{w.id}/agents/{agent_id}/versions").json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["snapshot"]["name"] == "Alpha v2"
    assert versions[1]["snapshot"]["name"] == "Alpha"
