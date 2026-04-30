"""Knowledge proxy in api-gateway: RBAC + forwarding + audit."""

from __future__ import annotations

import respx


def _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="builder@x")
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")
    login_as(u)
    return u, w


def test_search_requires_membership(client, make_tenant, make_user, make_workspace, login_as):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")  # not a member
    login_as(u)

    r = client.post(f"/api/v1/workspaces/{w.id}/search", json={"query": "hi"})
    assert r.status_code == 403


def test_search_proxies_to_knowledge_svc(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    upstream = {
        "query": "hello",
        "hits": [
            {
                "chunk_id": "00000000-0000-0000-0000-000000000001",
                "document_id": "00000000-0000-0000-0000-000000000002",
                "document_title": "Doc",
                "ord": 0,
                "text": "hello world",
                "score": 0.9,
                "meta": {},
            }
        ],
    }
    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://knowledge-svc:8084/search").respond(json=upstream)
        r = client.post(f"/api/v1/workspaces/{w.id}/search", json={"query": "hello"})
    assert r.status_code == 200
    assert r.json() == upstream
    # Workspace ID was injected by the gateway.
    sent = route.calls[0].request.read()
    assert str(w.id) in sent.decode()


def test_collection_create_emits_audit(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    upstream = {
        "id": "00000000-0000-0000-0000-000000000010",
        "workspace_id": str(w.id),
        "name": "Docs",
        "slug": "docs",
        "description": None,
        "created_at": "2026-04-30T00:00:00Z",
    }
    with respx.mock() as router:
        router.post(f"http://knowledge-svc:8084/workspaces/{w.id}/collections").respond(
            201, json=upstream
        )
        r = client.post(
            f"/api/v1/workspaces/{w.id}/collections",
            json={"name": "Docs", "slug": "docs"},
        )
    assert r.status_code == 201

    from agenticos_shared.models import AuditEventRow

    rows = db.query(AuditEventRow).filter_by(action="collection.create").all()
    assert len(rows) == 1


def test_document_upload_proxies_multipart(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    upstream = {
        "id": "00000000-0000-0000-0000-000000000020",
        "workspace_id": str(w.id),
        "collection_id": None,
        "title": "test.txt",
        "mime": "text/plain",
        "sha256": "abc",
        "size_bytes": 5,
        "status": "ready",
        "error": None,
        "chunk_count": 1,
        "meta": {},
        "created_at": "2026-04-30T00:00:00Z",
        "updated_at": "2026-04-30T00:00:00Z",
    }
    with respx.mock() as router:
        router.post(f"http://knowledge-svc:8084/workspaces/{w.id}/documents").respond(
            201, json=upstream
        )
        r = client.post(
            f"/api/v1/workspaces/{w.id}/documents",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
    assert r.status_code == 201
    assert r.json()["title"] == "test.txt"

    from agenticos_shared.models import AuditEventRow

    rows = db.query(AuditEventRow).filter_by(action="document.upload").all()
    assert len(rows) == 1


def test_member_role_cannot_upload(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="member")  # member can't write docs
    login_as(u)

    r = client.post(
        f"/api/v1/workspaces/{w.id}/documents",
        files={"file": ("x.txt", b"hi", "text/plain")},
    )
    assert r.status_code == 403
