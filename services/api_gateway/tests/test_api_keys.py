"""Workspace API keys: mint, list, revoke; bearer auth round-trip."""

from __future__ import annotations


def _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="admin@x", is_superuser=True)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="admin")
    login_as(u)
    return u, w


def test_create_returns_plaintext_once(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    r = client.post(
        f"/api/v1/workspaces/{w.id}/api-keys",
        json={"name": "ci", "scopes": ["read", "write"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"].startswith("aos_")
    assert body["prefix"] == body["token"][:8]
    assert body["scopes"] == ["read", "write"]

    # Listing must NOT include the plaintext.
    r2 = client.get(f"/api/v1/workspaces/{w.id}/api-keys")
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) == 1
    assert "token" not in rows[0]


def test_revoke_then_token_rejected(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    r = client.post(
        f"/api/v1/workspaces/{w.id}/api-keys",
        json={"name": "ci", "scopes": ["read"]},
    )
    plaintext = r.json()["token"]
    key_id = r.json()["id"]

    # Bearer works for /me.
    client.cookies.clear()
    r2 = client.get("/api/v1/me", headers={"Authorization": f"Bearer {plaintext}"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["email"].startswith(("admin@x", "svc:"))

    # Revoke (re-plant the existing user's session cookie; we cleared cookies
    # to test bearer auth above).
    from agenticos_shared.models import User as UserModel

    admin = db.query(UserModel).filter_by(email="admin@x").first()
    login_as(admin)
    r3 = client.delete(f"/api/v1/workspaces/{w.id}/api-keys/{key_id}")
    assert r3.status_code == 204

    # Now the bearer is unauthorized.
    client.cookies.clear()
    r4 = client.get("/api/v1/me", headers={"Authorization": f"Bearer {plaintext}"})
    assert r4.status_code == 401


def test_non_admin_cannot_create_key(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")  # not admin
    login_as(u)

    r = client.post(
        f"/api/v1/workspaces/{w.id}/api-keys",
        json={"name": "x"},
    )
    assert r.status_code == 403
