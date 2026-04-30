"""Embed chunks via the llm-gateway (OpenAI-compatible /v1/embeddings)."""

from __future__ import annotations

import httpx
from agenticos_shared.errors import AgenticOSError
from agenticos_shared.logging import get_logger

log = get_logger(__name__)


class EmbeddingError(AgenticOSError):
    status = 502
    code = "embedding_error"
    title = "Embedding service error"


class Embedder:
    def __init__(
        self,
        *,
        gateway_url: str,
        model_alias: str,
        timeout: float = 120.0,
        token: str | None = None,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.model_alias = model_alias
        self.timeout = timeout
        self.token = token

    @property
    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as c:
                r = await c.post(
                    f"{self.gateway_url}/v1/embeddings",
                    json={"model": self.model_alias, "input": texts},
                )
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"transport error: {exc}") from exc
        if r.status_code >= 400:
            raise EmbeddingError(f"gateway {r.status_code}: {r.text[:300]}")

        data = r.json()
        items = data.get("data") or []
        # OpenAI may return them out of order; sort by index.
        items.sort(key=lambda d: d.get("index", 0))
        return [list(d.get("embedding", [])) for d in items]
