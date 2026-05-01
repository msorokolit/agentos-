"""Async document upload + status polling proxy."""

from __future__ import annotations

from uuid import uuid4

import respx


def _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="b@x")
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")
    login_as(u)
    return u, w


def test_async_upload_propagates_202(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)

    upstream = {
        "id": str(uuid4()),
        "workspace_id": str(w.id),
        "collection_id": None,
        "title": "x.txt",
        "mime": "text/plain",
        "sha256": "abc",
        "size_bytes": 5,
        "status": "pending",
        "error": None,
        "chunk_count": 0,
        "meta": {"job_id": "job-1"},
        "created_at": "2026-04-30T00:00:00Z",
        "updated_at": "2026-04-30T00:00:00Z",
    }
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"http://knowledge-svc:8084/workspaces/{w.id}/documents/async").respond(
            202, json=upstream
        )
        r = client.post(
            f"/api/v1/workspaces/{w.id}/documents?async_ingest=true",
            files={"file": ("x.txt", b"hello", "text/plain")},
        )
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending"
    assert route.call_count == 1


def test_doc_status_proxy(client, make_tenant, make_user, make_workspace, add_member, login_as):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    doc_id = uuid4()
    with respx.mock(assert_all_called=True) as router:
        router.get(f"http://knowledge-svc:8084/documents/{doc_id}/status").respond(
            200,
            json={
                "id": str(doc_id),
                "status": "embedding",
                "chunk_count": 4,
                "error": None,
                "updated_at": "2026-04-30T00:00:00Z",
            },
        )
        r = client.get(f"/api/v1/workspaces/{w.id}/documents/{doc_id}/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "embedding"
    assert body["chunk_count"] == 4


def test_doc_status_requires_membership(client, make_tenant, make_user, make_workspace, login_as):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")  # not a member
    login_as(u)
    r = client.get(f"/api/v1/workspaces/{w.id}/documents/{uuid4()}/status")
    assert r.status_code == 403
