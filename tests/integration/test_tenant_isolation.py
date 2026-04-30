"""Cross-tenant isolation guarantees (PLAN §14 mitigation).

A user in tenant A must never reach data scoped to tenant B, even if
they know B's UUIDs. We exercise every workspace-scoped read + write
route and assert the api-gateway returns 404 (so we don't even leak
existence).
"""

from __future__ import annotations

import time
from uuid import UUID, uuid4

import pytest
from agenticos_shared.models import Tenant, User, Workspace, WorkspaceMember
from api_gateway.auth.session import SessionPayload, encode_session

SECRET = "test-secret-32-bytes-or-more!!!"


@pytest.fixture
def two_tenants(shared_session):
    tenant_a = Tenant(id=uuid4(), slug="acme", name="Acme")
    tenant_b = Tenant(id=uuid4(), slug="globex", name="Globex")
    shared_session.add_all([tenant_a, tenant_b])
    shared_session.flush()

    alice = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email="alice@acme",
        display_name="Alice",
    )
    bob = User(
        id=uuid4(),
        tenant_id=tenant_b.id,
        email="bob@globex",
        display_name="Bob",
    )
    shared_session.add_all([alice, bob])
    shared_session.flush()

    ws_a = Workspace(id=uuid4(), tenant_id=tenant_a.id, slug="default", name="Default")
    ws_b = Workspace(id=uuid4(), tenant_id=tenant_b.id, slug="default", name="Default")
    shared_session.add_all([ws_a, ws_b])
    shared_session.flush()

    shared_session.add_all(
        [
            WorkspaceMember(workspace_id=ws_a.id, user_id=alice.id, role="owner"),
            WorkspaceMember(workspace_id=ws_b.id, user_id=bob.id, role="owner"),
        ]
    )
    shared_session.commit()
    return alice, bob, ws_a, ws_b


def _login(client, user) -> None:
    now = int(time.time())
    cookie = encode_session(
        SessionPayload(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            display_name=user.display_name,
            issued_at=now,
            expires_at=now + 3600,
        ),
        secret=SECRET,
    )
    client.cookies.clear()
    client.cookies.set("agos_session", cookie)


def test_alice_can_see_only_her_workspace(api_client, two_tenants):
    alice, _bob, ws_a, ws_b = two_tenants
    _login(api_client, alice)

    listed = api_client.get("/api/v1/workspaces").json()
    seen_ids = {UUID(w["id"]) for w in listed}
    assert ws_a.id in seen_ids
    assert ws_b.id not in seen_ids


def test_alice_cannot_read_bobs_workspace(api_client, two_tenants):
    alice, _bob, _ws_a, ws_b = two_tenants
    _login(api_client, alice)

    # Direct GET on Bob's workspace id leaks no information.
    r = api_client.get(f"/api/v1/workspaces/{ws_b.id}")
    assert r.status_code == 404


def test_alice_cannot_list_bobs_members(api_client, two_tenants):
    alice, _bob, _ws_a, ws_b = two_tenants
    _login(api_client, alice)
    r = api_client.get(f"/api/v1/workspaces/{ws_b.id}/members")
    assert r.status_code == 404


def test_alice_cannot_create_in_bobs_workspace(api_client, two_tenants):
    alice, _bob, _ws_a, ws_b = two_tenants
    _login(api_client, alice)

    r = api_client.post(
        f"/api/v1/workspaces/{ws_b.id}/agents",
        json={"name": "evil", "slug": "evil", "model_alias": "chat-default"},
    )
    assert r.status_code == 404

    r = api_client.post(
        f"/api/v1/workspaces/{ws_b.id}/tools",
        json={"name": "evil", "kind": "builtin", "descriptor": {}},
    )
    assert r.status_code == 404

    r = api_client.post(
        f"/api/v1/workspaces/{ws_b.id}/collections",
        json={"name": "evil", "slug": "evil"},
    )
    assert r.status_code == 404

    r = api_client.post(f"/api/v1/workspaces/{ws_b.id}/search", json={"query": "x"})
    assert r.status_code == 404


def test_alice_cannot_read_bobs_audit(api_client, two_tenants):
    alice, _bob, _ws_a, ws_b = two_tenants
    _login(api_client, alice)
    r = api_client.get(f"/api/v1/workspaces/{ws_b.id}/audit")
    assert r.status_code == 404


def test_resource_lookup_across_workspaces_404(api_client, two_tenants):
    """An agent lives in Bob's workspace; Alice referring to it via
    her own workspace path must 404 rather than 403 or 200."""

    alice, bob, ws_a, ws_b = two_tenants

    # Bob creates an agent in his own workspace.
    _login(api_client, bob)
    r = api_client.post(
        f"/api/v1/workspaces/{ws_b.id}/agents",
        json={"name": "bobs", "slug": "bobs", "model_alias": "chat-default"},
    )
    assert r.status_code == 201
    bobs_agent = r.json()["id"]

    # Alice substitutes Bob's agent ID into her own workspace path.
    _login(api_client, alice)
    r = api_client.get(f"/api/v1/workspaces/{ws_a.id}/agents/{bobs_agent}/versions")
    assert r.status_code == 404
    r = api_client.patch(
        f"/api/v1/workspaces/{ws_a.id}/agents/{bobs_agent}",
        json={"name": "stolen"},
    )
    assert r.status_code == 404
    r = api_client.delete(f"/api/v1/workspaces/{ws_a.id}/agents/{bobs_agent}")
    assert r.status_code == 404


def test_session_messages_404_across_tenants(api_client, two_tenants):
    alice, bob, _ws_a, ws_b = two_tenants
    # Bob creates a session.
    _login(api_client, bob)
    r = api_client.post(
        f"/api/v1/workspaces/{ws_b.id}/agents",
        json={"name": "x", "slug": "x", "model_alias": "chat-default"},
    )
    agent_id = r.json()["id"]
    r = api_client.post(f"/api/v1/workspaces/{ws_b.id}/agents/{agent_id}/sessions", json={})
    sess_id = r.json()["id"]

    # Alice tries to read Bob's session via her workspace path — 404.
    _login(api_client, alice)
    r = api_client.get(f"/api/v1/workspaces/{ws_b.id}/sessions/{sess_id}/messages")
    assert r.status_code == 404
