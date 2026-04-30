"""End-to-end API tests with the embedder mocked."""

from __future__ import annotations

import respx


def _mock_embedder(router, dim: int = 4):
    def _vec(i: int) -> list[float]:
        v = [0.0] * dim
        v[i % dim] = 1.0
        return v

    async def handler(request):
        import httpx

        body = request.read()
        import json as _json

        payload = _json.loads(body)
        inputs = payload["input"] if isinstance(payload["input"], list) else [payload["input"]]
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": payload["model"],
                "data": [
                    {"object": "embedding", "embedding": _vec(i), "index": i}
                    for i in range(len(inputs))
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
            },
        )

    router.post("http://llm-gateway:8081/v1/embeddings").mock(side_effect=handler)


def test_collection_crud(client, workspace) -> None:
    r = client.post(
        f"/workspaces/{workspace.id}/collections",
        json={"name": "Docs", "slug": "docs"},
    )
    assert r.status_code == 201, r.text
    r2 = client.get(f"/workspaces/{workspace.id}/collections")
    assert r2.status_code == 200
    assert {c["slug"] for c in r2.json()} == {"docs"}


def test_collection_duplicate_slug_conflict(client, workspace) -> None:
    body = {"name": "Docs", "slug": "docs"}
    assert client.post(f"/workspaces/{workspace.id}/collections", json=body).status_code == 201
    r = client.post(f"/workspaces/{workspace.id}/collections", json=body)
    assert r.status_code == 409


def test_text_ingest_then_search(client, workspace) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_embedder(router)
        body = {
            "workspace_id": str(workspace.id),
            "title": "Brown Fox",
            "text": (
                "The quick brown fox jumps over the lazy dog.\n\n"
                "A second paragraph about something completely different."
            ),
        }
        r = client.post(f"/workspaces/{workspace.id}/documents/text", json=body)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "ready"
    assert doc["chunk_count"] >= 1

    # Search now hits hybrid path.
    with respx.mock(assert_all_called=False) as router:
        _mock_embedder(router)
        r2 = client.post(
            "/search",
            json={
                "workspace_id": str(workspace.id),
                "query": "brown fox",
                "top_k": 3,
            },
        )
    assert r2.status_code == 200
    body = r2.json()
    assert body["query"] == "brown fox"
    assert len(body["hits"]) >= 1
    assert any("fox" in h["text"].lower() for h in body["hits"])


def test_upload_pdf_creates_document(client, workspace) -> None:
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)

    with respx.mock(assert_all_called=False) as router:
        _mock_embedder(router)
        r = client.post(
            f"/workspaces/{workspace.id}/documents",
            files={"file": ("blank.pdf", buf.getvalue(), "application/pdf")},
        )
    # Empty PDF → 0 chunks but doc is "ready".
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["mime"] == "application/pdf"
    assert doc["status"] == "ready"


def test_text_ingest_with_failing_embedder_marks_doc_failed(client, workspace) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.post("http://llm-gateway:8081/v1/embeddings").respond(500, text="boom")
        r = client.post(
            f"/workspaces/{workspace.id}/documents/text",
            json={
                "workspace_id": str(workspace.id),
                "title": "Will fail",
                "text": "some content here please",
            },
        )
    assert r.status_code == 502
    # The document row should still exist with status=failed

    docs = client.get(f"/workspaces/{workspace.id}/documents").json()
    assert any(d["status"] == "failed" for d in docs)
    assert "Will fail" in {d["title"] for d in docs}
