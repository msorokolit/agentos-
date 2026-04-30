"""End-to-end v1 chat + embeddings via the FastAPI app."""

from __future__ import annotations

import httpx
import pytest
import respx


@pytest.fixture
def register_chat_model(client):
    r = client.post(
        "/admin/models",
        json={
            "alias": "chat-default",
            "provider": "ollama",
            "endpoint": "http://ollama:11434",
            "model_name": "qwen2.5:7b-instruct",
            "kind": "chat",
        },
    )
    assert r.status_code == 201
    return r.json()


@pytest.fixture
def register_embed_model(client):
    r = client.post(
        "/admin/models",
        json={
            "alias": "embed-default",
            "provider": "ollama",
            "endpoint": "http://ollama:11434",
            "model_name": "nomic-embed-text",
            "kind": "embedding",
        },
    )
    assert r.status_code == 201
    return r.json()


def test_chat_unknown_alias_404(client) -> None:
    r = client.post(
        "/v1/chat/completions",
        json={"model": "no-such-model", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_chat_kind_mismatch_validation_error(client, register_embed_model) -> None:
    r = client.post(
        "/v1/chat/completions",
        json={"model": "embed-default", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 422


def test_chat_routes_to_provider_and_records_usage(client, register_chat_model, db) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post("http://ollama:11434/api/chat").respond(
            json={
                "message": {"role": "assistant", "content": "Hello!"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": 2,
            }
        )
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "chat-default",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "chat-default"
    assert body["choices"][0]["message"]["content"] == "Hello!"
    assert body["usage"]["prompt_tokens"] == 5
    assert body["usage"]["completion_tokens"] == 2

    # Token usage row was written.
    from agenticos_shared.models import TokenUsage

    rows = db.query(TokenUsage).all()
    assert len(rows) == 1
    assert rows[0].model_alias == "chat-default"
    assert rows[0].prompt_tokens == 5
    assert rows[0].completion_tokens == 2


def test_chat_streaming_returns_sse(client, register_chat_model) -> None:
    import json

    body_lines = [
        json.dumps({"message": {"role": "assistant", "content": "Hi "}, "done": False}),
        json.dumps(
            {
                "message": {"role": "assistant", "content": "world"},
                "done": True,
                "done_reason": "stop",
            }
        ),
    ]
    payload = "\n".join(body_lines).encode()

    with respx.mock() as router:
        router.post("http://ollama:11434/api/chat").mock(
            return_value=httpx.Response(200, content=payload)
        )
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "chat-default",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        ) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            chunks = []
            for line in r.iter_lines():
                if line.startswith("data: "):
                    raw = line[len("data: ") :]
                    if raw == "[DONE]":
                        break
                    chunks.append(json.loads(raw))
    assert chunks
    assert chunks[0]["model"] == "chat-default"
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == "Hi world"


def test_embeddings_routes_to_provider(client, register_embed_model, db) -> None:
    with respx.mock() as router:
        router.post("http://ollama:11434/api/embeddings").mock(
            side_effect=[
                httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]}),
            ]
        )
        r = client.post(
            "/v1/embeddings",
            json={"model": "embed-default", "input": "hello"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "embed-default"
    assert body["data"][0]["embedding"] == [0.1, 0.2, 0.3]


def test_disabled_model_is_forbidden(client, register_chat_model) -> None:
    mid = register_chat_model["id"]
    client.patch(f"/admin/models/{mid}", json={"enabled": False})

    r = client.post(
        "/v1/chat/completions",
        json={"model": "chat-default", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 403
