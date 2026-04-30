"""rag_search built-in tool.

Forwards a search request to the knowledge-svc and returns shaped results
suitable for LLM consumption (truncated text + citation triples).
"""

from __future__ import annotations

from typing import Any

import httpx
from agenticos_shared.errors import ValidationError

_MAX_HIT_TEXT = 1200


async def rag_search(ctx: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    settings = ctx.get("settings")
    workspace_id = ctx.get("workspace_id")
    query = args.get("query")
    if not query:
        raise ValidationError("query is required")

    payload = {
        "workspace_id": str(workspace_id) if workspace_id else None,
        "query": query,
        "top_k": int(args.get("top_k", 5) or 5),
    }
    if args.get("collection_id"):
        payload["collection_id"] = str(args["collection_id"])

    timeout = float(getattr(settings, "invoke_timeout_seconds", 30.0) or 30.0)
    base = getattr(settings, "knowledge_svc_url", "http://knowledge-svc:8084").rstrip("/")
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{base}/search", json=payload)
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "detail": r.text[:300]}
    body = r.json()
    hits = []
    for h in body.get("hits", []):
        text = (h.get("text") or "")[:_MAX_HIT_TEXT]
        hits.append(
            {
                "document_title": h.get("document_title"),
                "document_id": h.get("document_id"),
                "ord": h.get("ord"),
                "score": h.get("score"),
                "text": text,
            }
        )
    return {"query": query, "hits": hits}
