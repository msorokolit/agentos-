"""Per-model cost tracking on /v1/chat/completions and /v1/embeddings."""

from __future__ import annotations

import respx
from agenticos_shared.models import TokenUsage


def _register(client, **overrides):
    body = {
        "alias": "chat-paid",
        "provider": "openai_compat",
        "endpoint": "http://vllm:8000",
        "model_name": "paid-model",
        "kind": "chat",
        "cost_per_1m_input_usd": 5.0,  # $5 / 1M in
        "cost_per_1m_output_usd": 15.0,  # $15 / 1M out
    }
    body.update(overrides)
    r = client.post("/admin/models", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_chat_records_cost_per_call(client, db) -> None:
    _register(client)
    upstream = {
        "id": "x",
        "object": "chat.completion",
        "created": 1,
        "model": "vllm-internal",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 1_000,
            "completion_tokens": 500,
            "total_tokens": 1_500,
        },
    }
    with respx.mock(assert_all_called=True) as router:
        router.post("http://vllm:8000/v1/chat/completions").respond(json=upstream)
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "chat-paid",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert r.status_code == 200, r.text
    usage = r.json()["usage"]
    # 1000 in @ $5/M + 500 out @ $15/M = 0.005 + 0.0075 = 0.0125
    assert usage["cost_usd"] == 0.0125

    rows = db.query(TokenUsage).all()
    assert len(rows) == 1
    assert abs(rows[0].cost_usd - 0.0125) < 1e-9


def test_embedding_records_input_cost(client, db) -> None:
    _register(
        client,
        alias="embed-paid",
        kind="embedding",
        cost_per_1m_input_usd=2.0,
        cost_per_1m_output_usd=0.0,
    )
    with respx.mock() as router:
        router.post("http://vllm:8000/v1/embeddings").respond(
            json={
                "object": "list",
                "model": "vllm-internal",
                "data": [{"object": "embedding", "embedding": [0.1, 0.2], "index": 0}],
                "usage": {"prompt_tokens": 4_000, "completion_tokens": 0, "total_tokens": 4_000},
            }
        )
        r = client.post(
            "/v1/embeddings",
            json={"model": "embed-paid", "input": "hi"},
        )
    assert r.status_code == 200, r.text
    # 4000 in @ $2/M = $0.008
    assert r.json()["usage"]["cost_usd"] == 0.008


def test_zero_cost_when_rates_unset(client, db) -> None:
    """Self-hosted models default to cost=0; usage row records 0."""

    r = client.post(
        "/admin/models",
        json={
            "alias": "chat-free",
            "provider": "ollama",
            "endpoint": "http://ollama:11434",
            "model_name": "qwen",
            "kind": "chat",
        },
    )
    assert r.status_code == 201
    upstream = {
        "message": {"role": "assistant", "content": "hi"},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 7,
        "eval_count": 3,
    }
    with respx.mock() as router:
        router.post("http://ollama:11434/api/chat").respond(json=upstream)
        r = client.post(
            "/v1/chat/completions",
            json={"model": "chat-free", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 200
    assert r.json()["usage"]["cost_usd"] == 0.0


def test_metrics_endpoint_includes_cost_counter(client) -> None:
    _register(client)
    with respx.mock() as router:
        router.post("http://vllm:8000/v1/chat/completions").respond(
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "vllm-internal",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hi"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 0,
                    "total_tokens": 1_000_000,
                },
            }
        )
        client.post(
            "/v1/chat/completions",
            json={"model": "chat-paid", "messages": [{"role": "user", "content": "hi"}]},
        )
    body = client.get("/metrics").text
    assert "llm_cost_usd_total" in body
    assert 'model="chat-paid"' in body
