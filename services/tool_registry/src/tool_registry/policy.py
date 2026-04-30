"""OPA policy client + cached evaluator.

Tool invocations are gated through ``decide_tool_access``. If OPA is
unreachable, we fail-closed unless ``AGENTICOS_ENV=test`` (default-allow
in tests so we don't need an OPA sidecar).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from agenticos_shared.logging import get_logger

log = get_logger(__name__)


class PolicyClient:
    def __init__(self, *, opa_url: str, timeout: float = 5.0) -> None:
        self.opa_url = opa_url.rstrip("/")
        self.timeout = timeout

    async def evaluate(
        self, package_path: str, *, input: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Return (allowed, reason)."""

        url = f"{self.opa_url}/v1/data/{package_path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(url, json={"input": input})
        except httpx.HTTPError as exc:
            log.warning("opa_unreachable", error=str(exc))
            if os.environ.get("AGENTICOS_ENV") == "test":
                return True, "opa_offline_test_default_allow"
            return False, f"opa unreachable: {exc}"

        if r.status_code >= 400:
            log.warning("opa_error", status=r.status_code, body=r.text[:300])
            return False, f"opa error {r.status_code}"
        body = r.json() or {}
        result = body.get("result")
        # The Rego file we ship sets `allow := false` by default and
        # rules add allowance: result is bool.
        if isinstance(result, dict) and "allow" in result:
            return bool(result["allow"]), None
        return bool(result), None


async def decide_tool_access(
    *,
    client: PolicyClient,
    principal_roles: list[str],
    workspace_ids: list[str],
    tool_id: str,
    tool_scopes: list[str],
    agent_allowed_tools: list[str] | None = None,
) -> tuple[bool, str | None]:
    inp = {
        "principal": {
            "roles": principal_roles,
            "workspace_ids": workspace_ids,
        },
        "tool": {
            "id": tool_id,
            "scopes": tool_scopes,
        },
        "agent": {"allowed_tools": agent_allowed_tools or [tool_id]},
    }
    return await client.evaluate("agenticos/tool_access", input=inp)
