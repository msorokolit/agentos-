"""Workspace + member CRUD + RBAC."""

from __future__ import annotations


def test_list_workspaces_filters_to_membership(
    client, make_tenant, make_user, make_workspace, add_member, login_as
) -> None:
    t = make_tenant()
    alice = make_user(t.id, email="alice@x")
    bob = make_user(t.id, email="bob@x")
    w1 = make_workspace(t.id, slug="alpha")
    w2 = make_workspace(t.id, slug="beta")
    add_member(w1.id, alice.id, role="member")
    add_member(w2.id, bob.id, role="member")

    login_as(alice)
    r = client.get("/api/v1/workspaces")
    assert r.status_code == 200
    body = r.json()
    slugs = {w["slug"] for w in body}
    assert slugs == {"alpha"}


def test_create_workspace_makes_creator_owner(client, make_tenant, make_user, login_as) -> None:
    t = make_tenant()
    alice = make_user(t.id)
    login_as(alice)

    r = client.post(
        "/api/v1/workspaces",
        json={"name": "My WS", "slug": "my-ws"},
    )
    assert r.status_code == 201, r.text
    ws_id = r.json()["id"]

    r2 = client.get(f"/api/v1/workspaces/{ws_id}")
    assert r2.status_code == 200

    me = client.get("/api/v1/me").json()
    assert any(w["workspace_slug"] == "my-ws" and w["role"] == "owner" for w in me["workspaces"])


def test_create_workspace_conflict_on_duplicate_slug(
    client, make_tenant, make_user, make_workspace, login_as
) -> None:
    t = make_tenant()
    alice = make_user(t.id)
    make_workspace(t.id, slug="dup")
    login_as(alice)

    r = client.post("/api/v1/workspaces", json={"name": "x", "slug": "dup"})
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"


def test_get_workspace_requires_membership(
    client, make_tenant, make_user, make_workspace, login_as
) -> None:
    t = make_tenant()
    alice = make_user(t.id)
    w = make_workspace(t.id, slug="alpha")  # alice is NOT a member
    login_as(alice)

    r = client.get(f"/api/v1/workspaces/{w.id}")
    assert r.status_code == 403


def test_update_workspace_requires_admin(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
) -> None:
    from agenticos_shared.models import WorkspaceMember

    t = make_tenant()
    alice = make_user(t.id)
    w = make_workspace(t.id, slug="alpha")
    add_member(w.id, alice.id, role="member")  # member can't update
    login_as(alice)

    r = client.patch(f"/api/v1/workspaces/{w.id}", json={"name": "renamed"})
    assert r.status_code == 403

    # Promote to admin (mutate the existing row) → can update.
    member = db.get(WorkspaceMember, (w.id, alice.id))
    member.role = "admin"
    db.commit()

    r = client.patch(f"/api/v1/workspaces/{w.id}", json={"name": "Renamed"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Renamed"


def test_delete_workspace_requires_owner(
    client, make_tenant, make_user, make_workspace, add_member, login_as
) -> None:
    t = make_tenant()
    alice = make_user(t.id)
    w = make_workspace(t.id, slug="alpha")
    add_member(w.id, alice.id, role="admin")  # admin is NOT owner
    login_as(alice)
    r = client.delete(f"/api/v1/workspaces/{w.id}")
    assert r.status_code == 403


def test_member_lifecycle(
    client, make_tenant, make_user, make_workspace, add_member, login_as
) -> None:
    t = make_tenant()
    alice = make_user(t.id, email="alice@x")
    bob = make_user(t.id, email="bob@x")
    w = make_workspace(t.id, slug="alpha")
    add_member(w.id, alice.id, role="admin")
    login_as(alice)

    # add bob
    r = client.post(
        f"/api/v1/workspaces/{w.id}/members",
        json={"email": "bob@x", "role": "member"},
    )
    assert r.status_code == 201
    assert r.json()["role"] == "member"

    # list
    r = client.get(f"/api/v1/workspaces/{w.id}/members")
    assert r.status_code == 200
    assert {m["email"] for m in r.json()} == {"alice@x", "bob@x"}

    # promote bob to builder
    r = client.patch(
        f"/api/v1/workspaces/{w.id}/members/{bob.id}",
        json={"role": "builder"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "builder"

    # remove bob
    r = client.delete(f"/api/v1/workspaces/{w.id}/members/{bob.id}")
    assert r.status_code == 204


def test_cannot_remove_last_owner(
    client, make_tenant, make_user, make_workspace, add_member, login_as
) -> None:
    t = make_tenant()
    alice = make_user(t.id)
    w = make_workspace(t.id, slug="alpha")
    add_member(w.id, alice.id, role="owner")
    login_as(alice)

    r = client.delete(f"/api/v1/workspaces/{w.id}/members/{alice.id}")
    assert r.status_code == 403
    assert "last owner" in r.json()["detail"]


def test_only_owner_can_promote_to_owner(
    client, make_tenant, make_user, make_workspace, add_member, login_as
) -> None:
    t = make_tenant()
    alice = make_user(t.id, email="alice@x")
    bob = make_user(t.id, email="bob@x")
    w = make_workspace(t.id, slug="alpha")
    add_member(w.id, alice.id, role="admin")  # admin, not owner
    add_member(w.id, bob.id, role="member")
    login_as(alice)

    r = client.patch(
        f"/api/v1/workspaces/{w.id}/members/{bob.id}",
        json={"role": "owner"},
    )
    assert r.status_code == 403
