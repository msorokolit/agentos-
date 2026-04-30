"""``POST /put`` and ``POST /get`` are aliases of ``/items`` and
``/search`` so they match the PLAN §4 internal-API verbs."""

from __future__ import annotations

import respx


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


def test_put_alias_creates_item(client, workspace) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_embedder(router)
        r = client.post(
            "/put",
            json={
                "workspace_id": str(workspace.id),
                "scope": "workspace",
                "key": "fact-1",
                "value": {"info": "founded 2026"},
                "summary": "founding",
                "embed": True,
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["key"] == "fact-1"
    assert body["has_embedding"] is True


def test_get_alias_returns_matches(client, workspace) -> None:
    # First seed a row via /items.
    with respx.mock(assert_all_called=False) as router:
        _mock_embedder(router)
        client.post(
            "/items",
            json={
                "workspace_id": str(workspace.id),
                "scope": "workspace",
                "key": "fact-1",
                "value": {},
                "summary": "founding",
                "embed": True,
            },
        )

    with respx.mock(assert_all_called=False) as router:
        _mock_embedder(router)
        r = client.post(
            "/get",
            json={
                "workspace_id": str(workspace.id),
                "scope": "workspace",
                "query": "When were we founded?",
                "top_k": 3,
            },
        )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) >= 1
    assert rows[0]["key"] == "fact-1"
