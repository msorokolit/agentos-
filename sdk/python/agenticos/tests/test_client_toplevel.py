"""Python SDK: top-level by-id methods."""

from __future__ import annotations

from uuid import uuid4

import pytest
import respx
from agenticos import AgenticOSClient

BASE = "http://api.test"


@pytest.fixture
def client() -> AgenticOSClient:
    c = AgenticOSClient(BASE, token="aos_test")
    yield c
    c.close()


def _agent_payload(workspace_id, agent_id, *, name="A", slug="a") -> dict:
    return {
        "id": str(agent_id),
        "workspace_id": str(workspace_id),
        "name": name,
        "slug": slug,
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


def test_session_top_level(client):
    aid = uuid4()
    sid = uuid4()
    wid = uuid4()
    with respx.mock(base_url=BASE) as router:
        router.post("/api/v1/sessions").respond(
            201,
            json={
                "id": str(sid),
                "agent_id": str(aid),
                "workspace_id": str(wid),
                "title": "ad-hoc",
                "created_at": "2026-04-30T00:00:00+00:00",
            },
        )
        s = client.session(aid, title="ad-hoc")
    assert s.id == sid
    assert s.agent_id == aid
    assert s.title == "ad-hoc"


def test_session_messages_top_level(client):
    sid = uuid4()
    with respx.mock(base_url=BASE) as router:
        router.get(f"/api/v1/sessions/{sid}/messages").respond(
            200,
            json=[
                {
                    "id": str(uuid4()),
                    "role": "user",
                    "content": "hi",
                    "tool_call": None,
                    "citations": [],
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "latency_ms": 0,
                    "created_at": "2026-04-30T00:00:00+00:00",
                },
            ],
        )
        msgs = client.session_messages(sid)
    assert len(msgs) == 1
    assert msgs[0].role == "user"


def test_get_patch_delete_run_agent(client):
    aid = uuid4()
    wid = uuid4()
    sid = uuid4()
    payload = _agent_payload(wid, aid)
    run_resp = {
        "final_message": "Hi!",
        "tool_calls": [],
        "tool_results": [],
        "citations": [],
        "iterations": 1,
        "tokens_in": 5,
        "tokens_out": 1,
        "error": None,
        "session_id": str(sid),
    }
    with respx.mock(base_url=BASE) as router:
        router.get(f"/api/v1/agents/{aid}").respond(json=payload)
        router.patch(f"/api/v1/agents/{aid}").respond(json={**payload, "name": "X"})
        router.delete(f"/api/v1/agents/{aid}").respond(204)
        router.post(f"/api/v1/agents/{aid}/run").respond(json=run_resp)

        a = client.get_agent(aid)
        assert a.id == aid
        a2 = client.patch_agent(aid, {"name": "X"})
        assert a2.name == "X"
        client.delete_agent_by_id(aid)
        out = client.run(aid, user_message="hi")
        assert out.final_message == "Hi!"
        assert out.session_id == sid


def test_get_document_top_level(client):
    did = uuid4()
    wid = uuid4()
    with respx.mock(base_url=BASE) as router:
        router.get(f"/api/v1/documents/{did}").respond(
            json={
                "id": str(did),
                "workspace_id": str(wid),
                "collection_id": None,
                "title": "x.txt",
                "mime": "text/plain",
                "sha256": "x",
                "size_bytes": 1,
                "status": "ready",
                "error": None,
                "chunk_count": 0,
                "meta": {},
                "created_at": "2026-04-30T00:00:00+00:00",
                "updated_at": "2026-04-30T00:00:00+00:00",
            }
        )
        d = client.get_document(did)
    assert d.id == did
    assert d.status == "ready"


def test_collection_search_top_level(client):
    cid = uuid4()
    with respx.mock(base_url=BASE) as router:
        route = router.post(f"/api/v1/collections/{cid}/search").respond(
            json={"query": "hi", "hits": []}
        )
        out = client.collection_search(cid, "hi", top_k=3)
    assert out.query == "hi"
    sent = route.calls[0].request.read().decode()
    assert '"top_k": 3' in sent or '"top_k":3' in sent
