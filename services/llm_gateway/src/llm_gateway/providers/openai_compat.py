"""OpenAI-compatible provider (vLLM, OpenAI proxies, llama.cpp server, ...).

Sends/receives the OpenAI HTTP shape as-is, only swapping the upstream
``model`` to our registered ``model_name``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import LLMProvider, ProviderError, ProviderTimeoutError


def _now() -> int:
    return int(time.time())


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


class OpenAICompatProvider(LLMProvider):
    name = "openai_compat"

    def __init__(
        self,
        *,
        endpoint: str,
        model_name: str,
        api_key: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model_name = model_name
        self._api_key = api_key
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _prep(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = dict(payload)
        body.pop("workspace_id", None)
        body["model"] = self.model_name
        body["stream"] = False
        return body

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = self._prep(payload)
        try:
            async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers) as c:
                r = await c.post(f"{self.endpoint}/v1/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"openai-compat timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"openai-compat error: {exc}") from exc

        if r.status_code >= 400:
            raise ProviderError(f"openai-compat {r.status_code}: {r.text[:300]}")
        data = r.json()
        # Force our model_name in response (some proxies echo the upstream id).
        data["model"] = self.model_name
        return data

    async def chat_stream(self, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        body = self._prep(payload)
        body["stream"] = True

        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers) as c:
            try:
                async with c.stream("POST", f"{self.endpoint}/v1/chat/completions", json=body) as r:
                    if r.status_code >= 400:
                        text = (await r.aread()).decode("utf-8", "replace")
                        raise ProviderError(f"openai-compat {r.status_code}: {text[:300]}")
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        event["model"] = self.model_name
                        yield event
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(f"openai-compat stream timeout: {exc}") from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"openai-compat stream error: {exc}") from exc

    async def embed(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = {"model": self.model_name, "input": payload["input"]}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers) as c:
                r = await c.post(f"{self.endpoint}/v1/embeddings", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"openai-compat embed timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"openai-compat embed error: {exc}") from exc

        if r.status_code >= 400:
            raise ProviderError(f"openai-compat embed {r.status_code}: {r.text[:300]}")
        data = r.json()
        data["model"] = self.model_name
        return data

    async def ping(self) -> int:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5.0, headers=self._headers) as c:
                r = await c.get(f"{self.endpoint}/v1/models")
                if r.status_code >= 500:
                    raise ProviderError(f"openai-compat {r.status_code}")
        except httpx.HTTPError as exc:
            raise ProviderError(f"openai-compat unreachable: {exc}") from exc
        return int((time.monotonic() - t0) * 1000)
