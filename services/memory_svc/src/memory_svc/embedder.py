"""Optional embedding helper for the memory service."""

from __future__ import annotations

import httpx


async def embed_one(
    *, gateway_url: str, model_alias: str, text: str, timeout: float = 30.0
) -> list[float] | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(
                f"{gateway_url.rstrip('/')}/v1/embeddings",
                json={"model": model_alias, "input": text},
            )
    except httpx.HTTPError:
        return None
    if r.status_code >= 400:
        return None
    data = r.json().get("data") or []
    if not data:
        return None
    return list(data[0].get("embedding") or [])
