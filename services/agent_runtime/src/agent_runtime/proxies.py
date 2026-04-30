"""Async clients for the LLM gateway, tool registry, and knowledge svc."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from agenticos_shared.errors import AgenticOSError


class ProxyError(AgenticOSError):
    status = 502
    code = "proxy_error"
    title = "Internal-service error"


class LLMProxy:
    def __init__(self, base_url: str, *, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(f"{self.base_url}/v1/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise ProxyError(f"llm-gateway transport error: {exc}") from exc
        if r.status_code >= 400:
            raise ProxyError(f"llm-gateway {r.status_code}: {r.text[:300]}")
        return r.json()


class ToolProxy:
    def __init__(self, base_url: str, *, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_for(self, workspace_id: UUID) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.get(f"{self.base_url}/tools", params={"workspace_id": str(workspace_id)})
        if r.status_code >= 400:
            raise ProxyError(f"tool-registry list {r.status_code}: {r.text[:300]}")
        return r.json()

    async def invoke(
        self, *, tool_id: str | None, name: str | None, workspace_id: UUID, args: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(
                    f"{self.base_url}/invoke",
                    json={
                        "tool_id": tool_id,
                        "name": name,
                        "workspace_id": str(workspace_id),
                        "args": args,
                    },
                )
        except httpx.HTTPError as exc:
            raise ProxyError(f"tool-registry transport error: {exc}") from exc
        if r.status_code >= 400:
            try:
                problem = r.json()
            except Exception:
                problem = {"detail": r.text}
            return {
                "ok": False,
                "error": problem.get("detail", r.text)[:500],
                "status": r.status_code,
            }
        return r.json()


class MemoryProxy:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def append_short_term(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
        role: str,
        content: str,
    ) -> None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                await c.post(
                    f"{self.base_url}/short-term/append",
                    json={
                        "workspace_id": str(workspace_id),
                        "session_id": str(session_id),
                        "role": role,
                        "content": content,
                    },
                )
        except httpx.HTTPError:
            return  # best-effort

    async def get_short_term(self, *, workspace_id: UUID, session_id: UUID) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(f"{self.base_url}/short-term/{workspace_id}/{session_id}")
        except httpx.HTTPError:
            return []
        if r.status_code >= 400:
            return []
        return list(r.json().get("messages") or [])


class KnowledgeProxy:
    def __init__(self, base_url: str, *, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search(
        self,
        *,
        workspace_id: UUID,
        query: str,
        top_k: int = 5,
        collection_id: UUID | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "workspace_id": str(workspace_id),
            "query": query,
            "top_k": top_k,
        }
        if collection_id is not None:
            payload["collection_id"] = str(collection_id)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(f"{self.base_url}/search", json=payload)
        except httpx.HTTPError as exc:
            raise ProxyError(f"knowledge-svc transport error: {exc}") from exc
        if r.status_code >= 400:
            return {"query": query, "hits": []}
        return r.json()
