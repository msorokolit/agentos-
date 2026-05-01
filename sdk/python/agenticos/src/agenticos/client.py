"""High-level AgenticOS client.

Targets the api-gateway. Handles auth via bearer (API key or session
cookie), maps RFC-7807 problem+json errors into :class:`AgenticOSAPIError`,
and exposes typed wrappers for the most common operations.

Both sync and async surfaces are provided:

>>> from agenticos import AgenticOSClient
>>> client = AgenticOSClient("http://localhost:8080", token="aos_...")
>>> me = client.me()
>>> client.close()

>>> async with AgenticOSClient("http://localhost:8080", token="aos_...") as c:
...     out = await c.aagents("ws-uuid")
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from .errors import AgenticOSAPIError
from .models import (
    Agent,
    Document,
    Member,
    Message,
    RunResult,
    SearchResponse,
    Session,
    Tool,
    Workspace,
)

_USER_AGENT = "agenticos-python-sdk/0.1.0"


def _raise_for_status(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    try:
        body = r.json()
    except Exception:
        body = {"detail": r.text}
    if isinstance(body, dict):
        raise AgenticOSAPIError(
            status=r.status_code,
            title=body.get("title"),
            code=body.get("code"),
            detail=body.get("detail"),
            body=body,
        )
    raise AgenticOSAPIError(status=r.status_code, body=body)


class AgenticOSClient:
    """Sync + async client for the AgenticOS API gateway."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = 60.0,
        verify: bool | str = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._timeout = timeout
        self._verify = verify
        self._sync: httpx.Client | None = None
        self._async: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Construction / lifecycle
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        h = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _client(self) -> httpx.Client:
        if self._sync is None:
            self._sync = httpx.Client(
                base_url=self.base_url,
                timeout=self._timeout,
                headers=self._headers(),
                verify=self._verify,
            )
        return self._sync

    def _aclient(self) -> httpx.AsyncClient:
        if self._async is None:
            self._async = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                headers=self._headers(),
                verify=self._verify,
            )
        return self._async

    def close(self) -> None:
        if self._sync is not None:
            self._sync.close()
            self._sync = None

    async def aclose(self) -> None:
        if self._async is not None:
            await self._async.aclose()
            self._async = None

    def __enter__(self) -> AgenticOSClient:
        self._client()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    async def __aenter__(self) -> AgenticOSClient:
        self._aclient()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        r = self._client().request(method, path, **kwargs)
        _raise_for_status(r)
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    async def _arequest(self, method: str, path: str, **kwargs: Any) -> Any:
        r = await self._aclient().request(method, path, **kwargs)
        _raise_for_status(r)
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    # ------------------------------------------------------------------
    # Health + auth
    # ------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return self._request("GET", "/healthz")

    async def ahealth(self) -> dict[str, Any]:
        return await self._arequest("GET", "/healthz")

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/me")

    async def ame(self) -> dict[str, Any]:
        return await self._arequest("GET", "/api/v1/me")

    # ------------------------------------------------------------------
    # Workspaces + members
    # ------------------------------------------------------------------
    def list_workspaces(self) -> list[Workspace]:
        rows = self._request("GET", "/api/v1/workspaces")
        return [Workspace.model_validate(r) for r in rows]

    def create_workspace(self, *, name: str, slug: str) -> Workspace:
        body = self._request("POST", "/api/v1/workspaces", json={"name": name, "slug": slug})
        return Workspace.model_validate(body)

    def list_members(self, workspace_id: UUID | str) -> list[Member]:
        rows = self._request("GET", f"/api/v1/workspaces/{workspace_id}/members")
        return [Member.model_validate(r) for r in rows]

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------
    def list_builtins(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/builtins")

    def list_tools(self, workspace_id: UUID | str) -> list[Tool]:
        rows = self._request("GET", f"/api/v1/workspaces/{workspace_id}/tools")
        return [Tool.model_validate(r) for r in rows]

    def create_tool(
        self,
        workspace_id: UUID | str,
        *,
        name: str,
        kind: str,
        descriptor: dict[str, Any],
        scopes: list[str] | None = None,
    ) -> Tool:
        body = self._request(
            "POST",
            f"/api/v1/workspaces/{workspace_id}/tools",
            json={
                "name": name,
                "kind": kind,
                "descriptor": descriptor,
                "scopes": scopes or [],
            },
        )
        return Tool.model_validate(body)

    def invoke_tool(
        self,
        workspace_id: UUID | str,
        tool_id: UUID | str,
        *,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/workspaces/{workspace_id}/tools/{tool_id}/invoke",
            json={"args": args or {}},
        )

    # ------------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------------
    def upload_document(
        self,
        workspace_id: UUID | str,
        file: Path | str,
        *,
        title: str | None = None,
        embed_alias: str | None = None,
    ) -> Document:
        path = Path(file)
        with path.open("rb") as fh:
            files = {"file": (path.name, fh, "application/octet-stream")}
            data = {}
            if title:
                data["title"] = title
            if embed_alias:
                data["embed_alias"] = embed_alias
            r = self._client().post(
                f"/api/v1/workspaces/{workspace_id}/documents",
                files=files,
                data=data,
            )
        _raise_for_status(r)
        return Document.model_validate(r.json())

    def list_documents(self, workspace_id: UUID | str) -> list[Document]:
        rows = self._request("GET", f"/api/v1/workspaces/{workspace_id}/documents")
        return [Document.model_validate(r) for r in rows]

    def search(
        self,
        workspace_id: UUID | str,
        query: str,
        *,
        top_k: int = 8,
        collection_id: UUID | str | None = None,
    ) -> SearchResponse:
        if collection_id is not None:
            path = f"/api/v1/workspaces/{workspace_id}/collections/{collection_id}/search"
        else:
            path = f"/api/v1/workspaces/{workspace_id}/search"
        body = self._request("POST", path, json={"query": query, "top_k": top_k})
        return SearchResponse.model_validate(body)

    # ------------------------------------------------------------------
    # Agents + chat
    # ------------------------------------------------------------------
    def list_agents(self, workspace_id: UUID | str) -> list[Agent]:
        rows = self._request("GET", f"/api/v1/workspaces/{workspace_id}/agents")
        return [Agent.model_validate(r) for r in rows]

    def create_agent(
        self,
        workspace_id: UUID | str,
        *,
        name: str,
        slug: str,
        model_alias: str,
        system_prompt: str = "",
        tool_ids: list[str] | None = None,
        config: dict[str, Any] | None = None,
        rag_collection_id: str | None = None,
    ) -> Agent:
        body = self._request(
            "POST",
            f"/api/v1/workspaces/{workspace_id}/agents",
            json={
                "name": name,
                "slug": slug,
                "model_alias": model_alias,
                "system_prompt": system_prompt,
                "tool_ids": tool_ids or [],
                "rag_collection_id": rag_collection_id,
                "config": config or {},
            },
        )
        return Agent.model_validate(body)

    def create_session(
        self, workspace_id: UUID | str, agent_id: UUID | str, *, title: str | None = None
    ) -> Session:
        body = self._request(
            "POST",
            f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}/sessions",
            json={"title": title} if title else {},
        )
        return Session.model_validate(body)

    # ---- top-level by-id helpers (PLAN §4) ----
    def session(self, agent_id: UUID | str, *, title: str | None = None) -> Session:
        """Top-level ``POST /api/v1/sessions``: resolves the workspace
        from the agent."""

        body: dict[str, Any] = {"agent_id": str(agent_id)}
        if title is not None:
            body["title"] = title
        out = self._request("POST", "/api/v1/sessions", json=body)
        return Session.model_validate(out)

    def session_messages(self, session_id: UUID | str) -> list[Message]:
        """Top-level ``GET /api/v1/sessions/{id}/messages``."""

        rows = self._request("GET", f"/api/v1/sessions/{session_id}/messages")
        return [Message.model_validate(r) for r in rows]

    def get_agent(self, agent_id: UUID | str) -> Agent:
        return Agent.model_validate(self._request("GET", f"/api/v1/agents/{agent_id}"))

    def patch_agent(self, agent_id: UUID | str, body: dict[str, Any]) -> Agent:
        return Agent.model_validate(self._request("PATCH", f"/api/v1/agents/{agent_id}", json=body))

    def delete_agent_by_id(self, agent_id: UUID | str) -> None:
        self._request("DELETE", f"/api/v1/agents/{agent_id}")

    def run(
        self,
        agent_id: UUID | str,
        *,
        user_message: str,
        session_id: UUID | str | None = None,
    ) -> RunResult:
        """Top-level ``POST /api/v1/agents/{id}/run``."""

        payload: dict[str, Any] = {"user_message": user_message}
        if session_id is not None:
            payload["session_id"] = str(session_id)
        return RunResult.model_validate(
            self._request("POST", f"/api/v1/agents/{agent_id}/run", json=payload)
        )

    def get_document(self, document_id: UUID | str) -> Document:
        return Document.model_validate(self._request("GET", f"/api/v1/documents/{document_id}"))

    def collection_search(
        self,
        collection_id: UUID | str,
        query: str,
        *,
        top_k: int = 8,
    ) -> SearchResponse:
        """Top-level ``POST /api/v1/collections/{id}/search``."""

        return SearchResponse.model_validate(
            self._request(
                "POST",
                f"/api/v1/collections/{collection_id}/search",
                json={"query": query, "top_k": top_k},
            )
        )

    def end_session(self, workspace_id: UUID | str, session_id: UUID | str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/workspaces/{workspace_id}/sessions/{session_id}/end")

    def list_messages(self, workspace_id: UUID | str, session_id: UUID | str) -> list[Message]:
        rows = self._request(
            "GET",
            f"/api/v1/workspaces/{workspace_id}/sessions/{session_id}/messages",
        )
        return [Message.model_validate(r) for r in rows]

    def run_agent(
        self,
        workspace_id: UUID | str,
        agent_id: UUID | str,
        *,
        user_message: str,
        session_id: UUID | str | None = None,
    ) -> RunResult:
        payload: dict[str, Any] = {"user_message": user_message}
        if session_id is not None:
            payload["session_id"] = str(session_id)
        body = self._request(
            "POST",
            f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}/run",
            json=payload,
        )
        return RunResult.model_validate(body)

    @contextmanager
    def stream_agent(
        self,
        workspace_id: UUID | str,
        agent_id: UUID | str,
        *,
        user_message: str,
        session_id: UUID | str | None = None,
    ) -> Iterator[Iterator[dict[str, Any]]]:
        """Server-sent events from /agents/{id}/run/stream — useful for tests
        and CLI tools that don't want to open a WebSocket.

        ``yield``s a generator of decoded JSON events.
        """

        payload: dict[str, Any] = {"user_message": user_message}
        if session_id is not None:
            payload["session_id"] = str(session_id)
        with self._client().stream(
            "POST",
            f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}/run/stream",
            json=payload,
        ) as r:
            _raise_for_status(r)

            def _iter() -> Iterator[dict[str, Any]]:
                for line in r.iter_lines():
                    if line.startswith("data: "):
                        raw = line[len("data: ") :]
                        if raw == "[DONE]":
                            return
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError:
                            continue

            yield _iter()
