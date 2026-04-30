"""Provider adapter unit tests with `respx` mocking."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from llm_gateway.providers.ollama import OllamaProvider
from llm_gateway.providers.openai_compat import OpenAICompatProvider


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ollama_chat_translates_payload() -> None:
    p = OllamaProvider(endpoint="http://ollama", model_name="qwen2.5:7b")
    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://ollama/api/chat").respond(
            json={
                "message": {"role": "assistant", "content": "hello"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 7,
                "eval_count": 3,
            }
        )
        out = await p.chat(
            {
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 0.5,
                "max_tokens": 32,
            }
        )

    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "qwen2.5:7b"
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0.5, "num_predict": 32}

    assert out["choices"][0]["message"]["content"] == "hello"
    assert out["usage"]["prompt_tokens"] == 7
    assert out["usage"]["completion_tokens"] == 3
    assert out["usage"]["total_tokens"] == 10


@pytest.mark.asyncio
async def test_ollama_chat_stream_yields_chunks() -> None:
    p = OllamaProvider(endpoint="http://ollama", model_name="m")

    body_lines = [
        json.dumps({"message": {"role": "assistant", "content": "Hi "}, "done": False}),
        json.dumps({"message": {"role": "assistant", "content": "there"}, "done": False}),
        json.dumps(
            {"message": {"role": "assistant", "content": "!"}, "done": True, "done_reason": "stop"}
        ),
    ]
    payload = "\n".join(body_lines).encode()

    with respx.mock() as router:
        router.post("http://ollama/api/chat").mock(
            return_value=httpx.Response(200, content=payload)
        )
        chunks = [c async for c in p.chat_stream({"messages": [{"role": "user", "content": "hi"}]})]

    assert len(chunks) == 3
    # First chunk announces the role
    assert chunks[0]["choices"][0]["delta"].get("role") == "assistant"
    # Last chunk has finish_reason
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == "Hi there!"


@pytest.mark.asyncio
async def test_ollama_embeddings_loops_inputs() -> None:
    p = OllamaProvider(endpoint="http://ollama", model_name="emb")
    with respx.mock(assert_all_called=True) as router:
        router.post("http://ollama/api/embeddings").mock(
            side_effect=[
                httpx.Response(200, json={"embedding": [0.1, 0.2]}),
                httpx.Response(200, json={"embedding": [0.3, 0.4]}),
            ]
        )
        out = await p.embed({"input": ["a", "b"]})
    assert len(out["data"]) == 2
    assert out["data"][0]["embedding"] == [0.1, 0.2]
    assert out["data"][1]["embedding"] == [0.3, 0.4]


# ---------------------------------------------------------------------------
# OpenAI-compatible (vLLM, etc.)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_openai_compat_chat_passthrough() -> None:
    p = OpenAICompatProvider(endpoint="http://vllm", model_name="my-model")
    with respx.mock() as router:
        route = router.post("http://vllm/v1/chat/completions").respond(
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
                "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            }
        )
        out = await p.chat({"messages": [{"role": "user", "content": "hi"}]})

    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "my-model"  # we override
    assert out["model"] == "my-model"  # response too
    assert out["choices"][0]["message"]["content"] == "hi"


@pytest.mark.asyncio
async def test_openai_compat_stream_parses_sse() -> None:
    p = OpenAICompatProvider(endpoint="http://vllm", model_name="m")
    sse = (
        b'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"u",'
        b'"choices":[{"index":0,"delta":{"role":"assistant","content":"A"},"finish_reason":null}]}\n\n'
        b'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"u",'
        b'"choices":[{"index":0,"delta":{"content":"B"},"finish_reason":null}]}\n\n'
        b"data: [DONE]\n\n"
    )
    with respx.mock() as router:
        router.post("http://vllm/v1/chat/completions").mock(
            return_value=httpx.Response(200, content=sse)
        )
        chunks = [c async for c in p.chat_stream({"messages": [{"role": "user", "content": "x"}]})]

    assert len(chunks) == 2
    assert chunks[0]["choices"][0]["delta"]["content"] == "A"
    assert chunks[1]["choices"][0]["delta"]["content"] == "B"
    assert all(c["model"] == "m" for c in chunks)


@pytest.mark.asyncio
async def test_openai_compat_5xx_raises_provider_error() -> None:
    from llm_gateway.providers.base import ProviderError

    p = OpenAICompatProvider(endpoint="http://vllm", model_name="m")
    with respx.mock() as router:
        router.post("http://vllm/v1/chat/completions").respond(500, text="boom")
        with pytest.raises(ProviderError):
            await p.chat({"messages": [{"role": "user", "content": "x"}]})
