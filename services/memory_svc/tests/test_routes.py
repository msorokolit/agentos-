"""End-to-end memory-svc API tests."""

from __future__ import annotations

import respx


def _mock_embedder(router):
    import httpx

    async def handler(request):
        body = request.read()
        import json

        payload = json.loads(body)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": payload["model"],
                "data": [{"object": "embedding", "embedding": [1.0, 0.0], "index": 0}],
            },
        )

    router.post("http://llm-gateway:8081/v1/embeddings").mock(side_effect=handler)


def test_short_term_roundtrip(client, workspace) -> None:
    from uuid import uuid4

    sess = uuid4()
    r = client.post(
        "/short-term/append",
        json={
            "workspace_id": str(workspace.id),
            "session_id": str(sess),
            "role": "user",
            "content": "hello",
        },
    )
    assert r.status_code == 200
    # Returns whatever the (possibly noop) Redis says.
    body = r.json()
    assert body["session_id"] == str(sess)


def test_put_and_search_long_term(client, workspace) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_embedder(router)
        r = client.post(
            "/items",
            json={
                "workspace_id": str(workspace.id),
                "scope": "workspace",
                "key": "fact-1",
                "value": {"role": "company", "info": "We were founded in 2020."},
                "summary": "founding year",
                "embed": True,
            },
        )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["has_embedding"] is True

    # Search via /search with a query (needs embedder again).
    with respx.mock(assert_all_called=False) as router:
        _mock_embedder(router)
        r2 = client.post(
            "/search",
            json={
                "workspace_id": str(workspace.id),
                "scope": "workspace",
                "query": "When were we founded?",
                "top_k": 3,
            },
        )
    assert r2.status_code == 200
    body = r2.json()
    assert len(body) >= 1
    assert body[0]["key"] == "fact-1"


def test_list_filter(client, workspace) -> None:
    client.post(
        "/items",
        json={
            "workspace_id": str(workspace.id),
            "scope": "workspace",
            "key": "k1",
            "value": {},
        },
    )
    client.post(
        "/items",
        json={
            "workspace_id": str(workspace.id),
            "scope": "user",
            "key": "k2",
            "value": {},
        },
    )
    r = client.get(
        f"/items?workspace_id={workspace.id}&scope=user",
    )
    assert r.status_code == 200
    rows = r.json()
    keys = {r["key"] for r in rows}
    assert keys == {"k2"}
