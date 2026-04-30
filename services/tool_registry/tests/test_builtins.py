"""Built-in tools (http_get, rag_search)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
import respx
from agenticos_shared.errors import ForbiddenError, ValidationError
from tool_registry.builtins.http_get import http_get
from tool_registry.builtins.rag_search import rag_search


@pytest.mark.asyncio
async def test_http_get_requires_url():
    with pytest.raises(ValidationError):
        await http_get({"settings": SimpleNamespace()}, {})


@pytest.mark.asyncio
async def test_http_get_strips_set_cookie_and_truncates():
    settings = SimpleNamespace(
        egress_allow_hosts=[], invoke_timeout_seconds=5.0, max_response_bytes=10
    )
    with respx.mock(assert_all_called=True) as router:
        router.get("https://example.com/hello").respond(
            200,
            content=b"Hello, world! more text",
            headers={"set-cookie": "x=1", "x-other": "ok"},
        )
        out = await http_get({"settings": settings}, {"url": "https://example.com/hello"})
    assert out["status"] == 200
    assert out["truncated"] is True
    assert out["bytes"] == 10
    assert "set-cookie" not in {k.lower() for k in out["headers"]}


@pytest.mark.asyncio
async def test_http_get_egress_allow_list_blocks_external():
    settings = SimpleNamespace(
        egress_allow_hosts=["allowed.example.com"],
        invoke_timeout_seconds=5.0,
        max_response_bytes=1024,
    )
    with pytest.raises(ForbiddenError):
        await http_get({"settings": settings}, {"url": "https://other.example.com/x"})


@pytest.mark.asyncio
async def test_http_get_egress_allow_list_passes_wildcard():
    settings = SimpleNamespace(
        egress_allow_hosts=["*.example.com"],
        invoke_timeout_seconds=5.0,
        max_response_bytes=1024,
    )
    with respx.mock() as router:
        router.get("https://api.example.com/x").respond(200, text="ok")
        out = await http_get({"settings": settings}, {"url": "https://api.example.com/x"})
    assert out["status"] == 200


@pytest.mark.asyncio
async def test_rag_search_forwards_to_knowledge_svc():
    settings = SimpleNamespace(
        knowledge_svc_url="http://knowledge-svc:8084",
        invoke_timeout_seconds=5.0,
    )
    ws = uuid4()
    with respx.mock() as router:
        router.post("http://knowledge-svc:8084/search").respond(
            200,
            json={
                "query": "fox",
                "hits": [
                    {
                        "chunk_id": str(uuid4()),
                        "document_id": str(uuid4()),
                        "document_title": "Doc",
                        "ord": 0,
                        "text": "x" * 2000,
                        "score": 0.9,
                        "meta": {},
                    }
                ],
            },
        )
        out = await rag_search(
            {"settings": settings, "workspace_id": ws},
            {"query": "fox", "top_k": 3},
        )
    assert out["query"] == "fox"
    assert len(out["hits"]) == 1
    # text truncated to _MAX_HIT_TEXT
    assert len(out["hits"][0]["text"]) <= 1200
