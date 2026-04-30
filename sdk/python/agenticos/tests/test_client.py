"""Python SDK: typed wrappers + error mapping."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
import respx
from agenticos import AgenticOSAPIError, AgenticOSClient

BASE = "http://api.test"


@pytest.fixture
def client() -> AgenticOSClient:
    c = AgenticOSClient(BASE, token="aos_test")
    yield c
    c.close()


def test_health(client):
    with respx.mock(base_url=BASE) as router:
        router.get("/healthz").respond(json={"status": "ok", "service": "api-gateway"})
        out = client.health()
    assert out == {"status": "ok", "service": "api-gateway"}


def test_authorization_header_sent(client):
    with respx.mock(base_url=BASE) as router:
        route = router.get("/api/v1/me").respond(
            json={
                "user_id": str(uuid4()),
                "tenant_id": str(uuid4()),
                "email": "x@y",
                "is_superuser": False,
                "workspaces": [],
            }
        )
        client.me()
    assert route.calls[0].request.headers["authorization"] == "Bearer aos_test"


def test_problem_json_error_maps_to_exception(client):
    with respx.mock(base_url=BASE) as router:
        router.get("/api/v1/me").respond(
            403,
            json={
                "type": "about:blank",
                "title": "Forbidden",
                "status": 403,
                "code": "forbidden",
                "detail": "no role",
            },
        )
        with pytest.raises(AgenticOSAPIError) as excinfo:
            client.me()
    e = excinfo.value
    assert e.status == 403
    assert e.code == "forbidden"
    assert e.title == "Forbidden"
    assert e.detail == "no role"


def test_create_workspace_returns_typed_model(client):
    ws_id = uuid4()
    tenant_id = uuid4()
    with respx.mock(base_url=BASE) as router:
        router.post("/api/v1/workspaces").respond(
            201,
            json={
                "id": str(ws_id),
                "tenant_id": str(tenant_id),
                "name": "Demo",
                "slug": "demo",
                "created_at": "2026-04-30T00:00:00+00:00",
            },
        )
        ws = client.create_workspace(name="Demo", slug="demo")
    assert ws.id == ws_id
    assert ws.slug == "demo"


def test_create_agent_then_run(client):
    ws_id = uuid4()
    agent_id = uuid4()
    session_id = uuid4()
    agent_payload = {
        "id": str(agent_id),
        "workspace_id": str(ws_id),
        "name": "A",
        "slug": "a",
        "description": None,
        "system_prompt": "",
        "model_alias": "chat-default",
        "graph_kind": "react",
        "config": {},
        "tool_ids": [],
        "rag_collection_id": None,
        "version": 1,
        "enabled": True,
        "created_at": "2026-04-30T00:00:00+00:00",
        "updated_at": "2026-04-30T00:00:00+00:00",
    }
    run_payload = {
        "final_message": "Hello!",
        "tool_calls": [],
        "tool_results": [],
        "citations": [],
        "iterations": 1,
        "tokens_in": 4,
        "tokens_out": 1,
        "error": None,
        "session_id": str(session_id),
    }

    with respx.mock(base_url=BASE) as router:
        router.post(f"/api/v1/workspaces/{ws_id}/agents").respond(201, json=agent_payload)
        router.post(f"/api/v1/workspaces/{ws_id}/agents/{agent_id}/run").respond(
            200, json=run_payload
        )

        agent = client.create_agent(ws_id, name="A", slug="a", model_alias="chat-default")
        out = client.run_agent(ws_id, agent.id, user_message="hi")

    assert agent.slug == "a"
    assert out.final_message == "Hello!"
    assert out.session_id == session_id


def test_search_typed(client):
    ws_id = uuid4()
    with respx.mock(base_url=BASE) as router:
        router.post(f"/api/v1/workspaces/{ws_id}/search").respond(
            200,
            json={
                "query": "foo",
                "hits": [
                    {
                        "chunk_id": str(uuid4()),
                        "document_id": str(uuid4()),
                        "document_title": "Doc",
                        "ord": 0,
                        "text": "foo bar",
                        "score": 0.9,
                        "meta": {},
                    }
                ],
            },
        )
        out = client.search(ws_id, "foo")
    assert out.query == "foo"
    assert len(out.hits) == 1
    assert out.hits[0].document_title == "Doc"


@pytest.mark.asyncio
async def test_async_client_health():
    async with AgenticOSClient(BASE, token="aos_test") as c:
        with respx.mock(base_url=BASE) as router:
            router.get("/healthz").respond(json={"status": "ok"})
            out = await c.ahealth()
    assert out == {"status": "ok"}


def test_stream_agent_yields_events():
    ws_id = uuid4()
    agent_id = uuid4()
    sse = (
        b'data: {"type":"step","payload":{"node":"plan"}}\n\n'
        b'data: {"type":"final","payload":{"content":"hi"}}\n\n'
        b"data: [DONE]\n\n"
    )
    with respx.mock(base_url=BASE) as router:
        router.post(f"/api/v1/workspaces/{ws_id}/agents/{agent_id}/run/stream").mock(
            return_value=httpx.Response(200, content=sse)
        )
        with (
            AgenticOSClient(BASE, token="aos_test") as c,
            c.stream_agent(ws_id, agent_id, user_message="x") as events,
        ):
            collected = list(events)
    assert [e["type"] for e in collected] == ["step", "final"]
    assert collected[1]["payload"]["content"] == "hi"
