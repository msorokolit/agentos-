"""Top-level GET /documents/{id} + POST /collections/{id}/search."""

from __future__ import annotations

from uuid import uuid4

import respx
from agenticos_shared.models import Collection, Document


def _login_member(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="member")
    login_as(u)
    return u, w


def _seed_doc(db, ws_id) -> Document:
    d = Document(
        id=uuid4(),
        workspace_id=ws_id,
        title="x.txt",
        mime="text/plain",
        sha256="x",
        size_bytes=1,
        status="ready",
        chunk_count=2,
        meta={},
    )
    db.add(d)
    db.commit()
    return d


def test_get_document_top_level_proxies(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_member(client, make_tenant, make_user, make_workspace, add_member, login_as)
    d = _seed_doc(db, w.id)
    upstream = {
        "id": str(d.id),
        "workspace_id": str(w.id),
        "collection_id": None,
        "title": "x.txt",
        "mime": "text/plain",
        "sha256": "x",
        "size_bytes": 1,
        "status": "ready",
        "error": None,
        "chunk_count": 2,
        "meta": {},
        "created_at": "2026-04-30T00:00:00Z",
        "updated_at": "2026-04-30T00:00:00Z",
    }
    with respx.mock(assert_all_called=True) as router:
        router.get(f"http://knowledge-svc:8084/documents/{d.id}").respond(json=upstream)
        r = client.get(f"/api/v1/documents/{d.id}")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == str(d.id)


def test_get_document_unknown_404(client, make_tenant, make_user, login_as):
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    r = client.get(f"/api/v1/documents/{uuid4()}")
    assert r.status_code == 404


def test_get_document_cross_tenant_404(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    """Bob's doc must 404 when fetched by Alice."""

    a_t = make_tenant(slug="acme")
    alice = make_user(a_t.id, email="alice@a")
    a_w = make_workspace(a_t.id, slug="alpha")
    add_member(a_w.id, alice.id, role="member")

    b_t = make_tenant(slug="globex")
    b_w = make_workspace(b_t.id, slug="bravo")
    bobs = _seed_doc(db, b_w.id)

    login_as(alice)
    r = client.get(f"/api/v1/documents/{bobs.id}")
    assert r.status_code == 404


def test_collection_search_top_level_injects_ws_and_collection(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_member(client, make_tenant, make_user, make_workspace, add_member, login_as)
    coll = Collection(id=uuid4(), workspace_id=w.id, slug="docs", name="Docs")
    db.add(coll)
    db.commit()

    upstream = {"query": "x", "hits": []}
    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://knowledge-svc:8084/search").respond(json=upstream)
        r = client.post(
            f"/api/v1/collections/{coll.id}/search",
            json={"query": "x", "top_k": 4},
        )
    assert r.status_code == 200, r.text
    sent = route.calls[0].request.read().decode()
    assert str(w.id) in sent
    assert str(coll.id) in sent
    assert '"top_k": 4' in sent or '"top_k":4' in sent


def test_collection_search_unknown_404(client, make_tenant, make_user, login_as):
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    r = client.post(f"/api/v1/collections/{uuid4()}/search", json={"query": "x"})
    assert r.status_code == 404


def test_collection_search_cross_tenant_404(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    a_t = make_tenant(slug="acme")
    alice = make_user(a_t.id, email="alice@a")
    a_w = make_workspace(a_t.id, slug="alpha")
    add_member(a_w.id, alice.id, role="member")

    b_t = make_tenant(slug="globex")
    b_w = make_workspace(b_t.id, slug="bravo")
    bob_coll = Collection(id=uuid4(), workspace_id=b_w.id, slug="bobs", name="Bobs")
    db.add(bob_coll)
    db.commit()

    login_as(alice)
    r = client.post(f"/api/v1/collections/{bob_coll.id}/search", json={"query": "hi"})
    assert r.status_code == 404
