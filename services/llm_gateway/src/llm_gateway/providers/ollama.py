"""Ollama provider adapter.

Translates OpenAI-shaped chat/embedding payloads into Ollama's native
``/api/chat`` and ``/api/embeddings`` shapes, and back.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import LLMProvider, ProviderError, ProviderTimeoutError


def _to_ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        # Ollama supports system/user/assistant/tool similarly to OpenAI.
        msg: dict[str, Any] = {"role": m["role"]}
        content = m.get("content")
        if isinstance(content, list):
            # Crude multi-part flattener: concatenate text parts.
            msg["content"] = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        else:
            msg["content"] = content or ""
        if m.get("tool_calls"):
            msg["tool_calls"] = m["tool_calls"]
        if m.get("name"):
            msg["name"] = m["name"]
        out.append(msg)
    return out


def _options_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    opts: dict[str, Any] = {}
    if payload.get("temperature") is not None:
        opts["temperature"] = payload["temperature"]
    if payload.get("top_p") is not None:
        opts["top_p"] = payload["top_p"]
    if payload.get("max_tokens") is not None:
        opts["num_predict"] = payload["max_tokens"]
    if payload.get("stop") is not None:
        stop = payload["stop"]
        opts["stop"] = stop if isinstance(stop, list) else [stop]
    return opts


def _now() -> int:
    return int(time.time())


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, *, endpoint: str, model_name: str, timeout: float = 120.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model_name = model_name
        self._timeout = timeout

    # -------------------- chat (non-stream) --------------------
    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.model_name,
            "messages": _to_ollama_messages(payload["messages"]),
            "stream": False,
            "options": _options_from_payload(payload),
        }
        if payload.get("tools"):
            body["tools"] = payload["tools"]
        if payload.get("response_format", {}).get("type") == "json_object":
            body["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.post(f"{self.endpoint}/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"ollama timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama transport error: {exc}") from exc

        if r.status_code >= 400:
            raise ProviderError(f"ollama {r.status_code}: {r.text[:300]}")
        data = r.json()

        msg = data.get("message", {}) or {}
        return {
            "id": _gen_id("chatcmpl"),
            "object": "chat.completion",
            "created": _now(),
            "model": self.model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": msg.get("role", "assistant"),
                        "content": msg.get("content", ""),
                        "tool_calls": msg.get("tool_calls"),
                    },
                    "finish_reason": "stop"
                    if data.get("done_reason") in (None, "stop")
                    else data.get("done_reason"),
                }
            ],
            "usage": {
                "prompt_tokens": int(data.get("prompt_eval_count", 0) or 0),
                "completion_tokens": int(data.get("eval_count", 0) or 0),
                "total_tokens": int(
                    (data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0)
                ),
            },
        }

    # -------------------- chat (stream) --------------------
    async def chat_stream(self, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        body = {
            "model": self.model_name,
            "messages": _to_ollama_messages(payload["messages"]),
            "stream": True,
            "options": _options_from_payload(payload),
        }
        if payload.get("tools"):
            body["tools"] = payload["tools"]

        chunk_id = _gen_id("chatcmpl")
        first = True
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            try:
                async with c.stream("POST", f"{self.endpoint}/api/chat", json=body) as r:
                    if r.status_code >= 400:
                        text = (await r.aread()).decode("utf-8", "replace")
                        raise ProviderError(f"ollama {r.status_code}: {text[:300]}")
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        msg = event.get("message", {}) or {}
                        delta: dict[str, Any] = {}
                        if first:
                            delta["role"] = msg.get("role", "assistant")
                            first = False
                        if msg.get("content"):
                            delta["content"] = msg["content"]
                        if msg.get("tool_calls"):
                            delta["tool_calls"] = msg["tool_calls"]

                        finish = None
                        if event.get("done"):
                            finish = "stop"

                        yield {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": _now(),
                            "model": self.model_name,
                            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                        }
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(f"ollama stream timeout: {exc}") from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"ollama stream error: {exc}") from exc

    # -------------------- embeddings --------------------
    async def embed(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Ollama only embeds one input at a time; loop for lists.
        inputs = payload["input"]
        if isinstance(inputs, str):
            inputs = [inputs]
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                results: list[list[float]] = []
                for text in inputs:
                    r = await c.post(
                        f"{self.endpoint}/api/embeddings",
                        json={"model": self.model_name, "prompt": text},
                    )
                    if r.status_code >= 400:
                        raise ProviderError(f"ollama embed {r.status_code}: {r.text[:300]}")
                    data = r.json()
                    results.append(list(data.get("embedding", [])))
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"ollama embed timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama embed error: {exc}") from exc

        return {
            "object": "list",
            "model": self.model_name,
            "data": [
                {"object": "embedding", "embedding": vec, "index": i}
                for i, vec in enumerate(results)
            ],
            "usage": {
                "prompt_tokens": sum(len(t.split()) for t in inputs),
                "completion_tokens": 0,
                "total_tokens": sum(len(t.split()) for t in inputs),
            },
        }

    # -------------------- ping --------------------
    async def ping(self) -> int:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{self.endpoint}/")
                if r.status_code >= 400:
                    raise ProviderError(f"ollama {r.status_code}")
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama unreachable: {exc}") from exc
        return int((time.monotonic() - t0) * 1000)
