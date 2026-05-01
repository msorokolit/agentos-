"""collection_document many-to-many join (PLAN §3)."""

from __future__ import annotations

from uuid import uuid4

import respx
from agenticos_shared.models import CollectionDocument


def _mock_embedder(router):
    import httpx

    router.post("http://llm-gateway:8081/v1/embeddings").mock(
        side_effect=lambda r: httpx.Response(
            200,
            json={
                "object": "list",
                "model": "embed-default",
                "data": [{"object": "embedding", "embedding": [1.0, 0.0], "index": 0}],
            },
        )
    )


def _make_collection(client, workspace, slug="docs") -> str:
    r = client.post(
        f"/workspaces/{workspace.id}/collections",
        json={"name": slug.title(), "slug": slug},
    )
    return r.json()["id"]


def _ingest(client, workspace, collection_id=None, title="x"):
    body = {
        "workspace_id": str(workspace.id),
        "title": title,
        "text": "Hello, world!",
    }
    if collection_id:
        body["collection_id"] = collection_id
    with respx.mock(assert_all_called=False) as router:
        _mock_embedder(router)
        r = client.post(f"/workspaces/{workspace.id}/documents/text", json=body)
    return r.json()["id"]


def test_primary_collection_mirrored_into_join_table(client, db, workspace):
    coll = _make_collection(client, workspace)
    doc_id = _ingest(client, workspace, collection_id=coll)
    rows = db.query(CollectionDocument).all()
    assert any(str(r.collection_id) == coll and str(r.document_id) == doc_id for r in rows)


def test_explicit_link_unlink(client, db, workspace):
    a = _make_collection(client, workspace, "alpha")
    b = _make_collection(client, workspace, "bravo")
    doc_id = _ingest(client, workspace, collection_id=a)

    # Link doc to collection b too.
    r = client.post(f"/collections/{b}/documents/{doc_id}")
    assert r.status_code == 204

    # Listing collection b shows the doc.
    r2 = client.get(f"/collections/{b}/documents")
    assert r2.status_code == 200
    assert any(d["id"] == doc_id for d in r2.json())

    # Unlink.
    r3 = client.delete(f"/collections/{b}/documents/{doc_id}")
    assert r3.status_code == 204
    from uuid import UUID

    assert (
        db.query(CollectionDocument)
        .filter_by(collection_id=UUID(b), document_id=UUID(doc_id))
        .count()
        == 0
    )


def test_link_validates_workspace_match(client, db, workspace):
    """Linking a doc to a collection in a different workspace is 422."""

    from uuid import uuid4 as _uuid

    from agenticos_shared.models import Tenant, Workspace

    # Build a second workspace with a collection.
    t2 = Tenant(id=_uuid(), slug="globex", name="Globex")
    db.add(t2)
    db.flush()
    w2 = Workspace(id=_uuid(), tenant_id=t2.id, slug="default", name="Default")
    db.add(w2)
    db.commit()

    coll_w2 = client.post(
        f"/workspaces/{w2.id}/collections",
        json={"name": "Other", "slug": "other"},
    ).json()["id"]
    doc_w1 = _ingest(client, workspace, title="w1-doc")

    r = client.post(f"/collections/{coll_w2}/documents/{doc_w1}")
    assert r.status_code == 422


def test_unknown_link_404(client, workspace):
    r = client.delete(f"/collections/{uuid4()}/documents/{uuid4()}")
    assert r.status_code == 404
