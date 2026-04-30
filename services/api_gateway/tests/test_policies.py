"""Policy bundle CRUD + activation."""

from __future__ import annotations

import respx


def _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="admin@x", is_superuser=True)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="admin")
    login_as(u)
    return u, w


REGO = """\
package agenticos.tool_access
default allow := false
allow if input.principal.roles[_] == "owner"
"""


def test_upload_then_list(client, make_tenant, make_user, make_workspace, add_member, login_as):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    r = client.post(
        "/api/v1/admin/policies",
        json={
            "package": "tool_access",
            "name": "default",
            "rego": REGO,
            "description": "starter",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"] == 1
    assert body["active"] is False
    assert len(body["sha256"]) == 64

    r2 = client.get("/api/v1/admin/policies")
    assert r2.status_code == 200
    assert any(b["name"] == "default" for b in r2.json())


def test_upload_with_activate_supersedes_previous(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    with respx.mock(assert_all_called=False) as router:
        opa_route = router.put(url__regex=r"http://[^/]+/v1/policies/.*").respond(200)
        # v1 active.
        r = client.post(
            "/api/v1/admin/policies",
            json={"package": "tool_access", "name": "default", "rego": REGO, "activate": True},
        )
        assert r.status_code == 201
        v1_id = r.json()["id"]
        assert r.json()["active"] is True

        # v2 active — supersedes v1.
        r = client.post(
            "/api/v1/admin/policies",
            json={
                "package": "tool_access",
                "name": "default",
                "rego": REGO + "\n# tweak\n",
                "activate": True,
            },
        )
        assert r.status_code == 201
        assert r.json()["version"] == 2

    actives = client.get("/api/v1/admin/policies?active_only=true").json()
    assert sum(1 for b in actives if b["package"] == "tool_access") == 1
    assert all(b["id"] != v1_id for b in actives)
    # The Rego was pushed to OPA at activation time (twice — once per
    # activate call).
    assert opa_route.call_count == 2


def test_activate_pushes_rego_to_opa(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    # Upload without activate first.
    r = client.post(
        "/api/v1/admin/policies",
        json={"package": "tool_access", "name": "default", "rego": REGO},
    )
    bid = r.json()["id"]

    with respx.mock(assert_all_called=True) as router:
        route = router.put(url__regex=r"http://[^/]+/v1/policies/.*").respond(200)
        r = client.post(f"/api/v1/admin/policies/{bid}/activate")
    assert r.status_code == 200
    assert r.json()["active"] is True
    sent = route.calls[0].request.read().decode()
    assert "package agenticos.tool_access" in sent
    # OPA path namespaced by tenant + package + name.
    target_url = str(route.calls[0].request.url)
    assert "/v1/policies/agenticos__" in target_url
    assert "__tool_access__default" in target_url


def test_delete_inactive_bundle_also_deletes_from_opa(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    r = client.post(
        "/api/v1/admin/policies",
        json={
            "package": "data_access",
            "name": "default",
            "rego": REGO.replace("tool_access", "data_access"),
        },
    )
    bid = r.json()["id"]

    with respx.mock(assert_all_called=True) as router:
        route = router.delete(url__regex=r"http://[^/]+/v1/policies/.*").respond(200)
        r = client.delete(f"/api/v1/admin/policies/{bid}")
    assert r.status_code == 204
    assert route.call_count == 1


def test_cannot_delete_active_bundle(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    r = client.post(
        "/api/v1/admin/policies",
        json={"package": "tool_access", "name": "default", "rego": REGO, "activate": True},
    )
    bid = r.json()["id"]
    r2 = client.delete(f"/api/v1/admin/policies/{bid}")
    assert r2.status_code == 422
    assert "active" in r2.json()["detail"]


def test_invalid_rego_rejected(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    r = client.post(
        "/api/v1/admin/policies",
        json={"package": "tool_access", "name": "x", "rego": "no package directive here"},
    )
    assert r.status_code == 422


def test_non_admin_blocked(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")
    login_as(u)

    r = client.get("/api/v1/admin/policies")
    assert r.status_code == 403
