"""GET /me — requires login, returns workspace memberships."""

from __future__ import annotations


def test_me_unauthenticated(client) -> None:
    r = client.get("/api/v1/me")
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "unauthorized"


def test_me_authenticated(
    client, make_tenant, make_user, make_workspace, add_member, login_as
) -> None:
    t = make_tenant("acme")
    u = make_user(t.id, email="alice@acme.local")
    w = make_workspace(t.id, slug="default", name="Default")
    add_member(w.id, u.id, role="admin")
    login_as(u)

    r = client.get("/api/v1/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "alice@acme.local"
    assert body["tenant_id"] == str(t.id)
    assert len(body["workspaces"]) == 1
    assert body["workspaces"][0]["role"] == "admin"
    assert body["workspaces"][0]["workspace_slug"] == "default"
