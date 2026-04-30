"""Minimal MCP (Model Context Protocol) HTTP client.

This implements the JSON-RPC subset we need to call MCP servers exposing
the **streamable HTTP transport** (POST + SSE). We deliberately do NOT
spawn stdio subprocesses — that's a Phase 1.5 concern (sandboxing).

For most internal tools, registering an HTTP/OpenAPI tool is simpler.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from agenticos_shared.errors import AgenticOSError


class MCPError(AgenticOSError):
    status = 502
    code = "mcp_error"
    title = "MCP error"


class MCPClient:
    def __init__(
        self, *, endpoint: str, headers: dict[str, str] | None = None, timeout: float = 30.0
    ):
        self.endpoint = endpoint.rstrip("/")
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.timeout = timeout

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": method,
            "params": params or {},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as c:
                r = await c.post(self.endpoint, json=body)
        except httpx.HTTPError as exc:
            raise MCPError(f"MCP transport error: {exc}") from exc
        if r.status_code >= 400:
            raise MCPError(f"MCP {r.status_code}: {r.text[:300]}")

        # Some MCP servers respond with SSE; handle both.
        ct = r.headers.get("content-type", "")
        if "text/event-stream" in ct:
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    try:
                        return json.loads(line[len("data:") :].strip())
                    except json.JSONDecodeError:
                        continue
            raise MCPError("MCP SSE response had no JSON event")
        try:
            return r.json()
        except json.JSONDecodeError as exc:
            raise MCPError(f"MCP non-JSON response: {exc}") from exc

    async def list_tools(self) -> list[dict[str, Any]]:
        out = await self._rpc("tools/list")
        result = out.get("result") or {}
        return list(result.get("tools") or [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        out = await self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        if "error" in out:
            return {"ok": False, "error": out["error"]}
        return {"ok": True, "result": out.get("result")}
