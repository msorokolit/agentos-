"""Async document ingestion (PLAN §4 ⇒ 202 + job_id) and the
``GET /documents/{id}/status`` polling endpoint."""

from __future__ import annotations

from agenticos_shared.models import Document


def test_async_upload_falls_back_when_no_worker(client, workspace, monkeypatch):
    """Without a reachable redis the route should still ingest inline
    and return 201, so dev/tests work without an external worker."""

    # Force the queue to look unavailable.
    from knowledge_svc import queue as q

    monkeypatch.setattr(q, "_pool", None)

    import respx

    with respx.mock(assert_all_called=False) as router:
        router.post("http://llm-gateway:8081/v1/embeddings").respond(
            200,
            json={
                "object": "list",
                "model": "embed-default",
                "data": [{"object": "embedding", "embedding": [1.0, 0.0], "index": 0}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
            },
        )
        r = client.post(
            f"/workspaces/{workspace.id}/documents/async",
            files={"file": ("note.txt", b"hello there", "text/plain")},
        )
    assert r.status_code == 201, r.text  # fallback path completed inline
    body = r.json()
    assert body["status"] == "ready"
    assert body["chunk_count"] >= 1


def test_async_upload_returns_202_when_worker_available(client, workspace, monkeypatch):
    """When the queue accepts the job we return 202 + a doc with
    ``status=pending`` and a ``job_id`` recorded in meta."""

    async def fake_enqueue(name, *args, **kwargs):
        return "job-abc-123"

    # The route imports ``enqueue`` from ``.queue`` so we have to patch
    # the *bound* name on the routes module too.
    from knowledge_svc import queue as q
    from knowledge_svc import routes as r

    monkeypatch.setattr(q, "enqueue", fake_enqueue)
    monkeypatch.setattr(r, "enqueue", fake_enqueue)

    r = client.post(
        f"/workspaces/{workspace.id}/documents/async",
        files={"file": ("note.txt", b"hello there", "text/plain")},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["meta"]["job_id"] == "job-abc-123"
    assert body["meta"]["s3_key"].startswith("uploads/")


def test_document_status_endpoint_returns_progress(client, workspace, db):
    from uuid import uuid4

    d = Document(
        id=uuid4(),
        workspace_id=workspace.id,
        title="x.txt",
        mime="text/plain",
        sha256="x",
        size_bytes=1,
        status="embedding",
        chunk_count=3,
        meta={},
    )
    db.add(d)
    db.commit()

    r = client.get(f"/documents/{d.id}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(d.id)
    assert body["status"] == "embedding"
    assert body["chunk_count"] == 3


def test_document_status_404_for_unknown(client):
    from uuid import uuid4

    r = client.get(f"/documents/{uuid4()}/status")
    assert r.status_code == 404
