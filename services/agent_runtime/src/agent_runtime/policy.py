"""OPA policy client for the ReAct graph.

We call ``POST /v1/data/agenticos/tool_access`` with::

    {
      "input": {
        "principal": { "roles": [...], "workspace_ids": ["..."] },
        "tool": { "id": "...", "name": "...", "scopes": [...] },
        "agent": { "allowed_tools": [...], "id": "..." },
        "args_summary": { "keys": [...], "n_args": N }
      }
    }

and accept either ``result.allow:bool`` or a bare boolean.

If OPA is unreachable we fail-**open** in test/dev (so the in-process
test suite doesn't need an OPA sidecar) and fail-**closed** in
``AGENTICOS_ENV=production``. The decision (allow/deny + reason) is
returned to the caller for audit + step events.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from agenticos_shared.logging import get_logger
from agenticos_shared.metrics import record_policy_decision

log = get_logger(__name__)


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str | None = None


def _summarise_args(args: dict[str, Any]) -> dict[str, Any]:
    """Lossy summary of tool args used by Rego rules (no payload leakage)."""

    keys = sorted(args.keys()) if isinstance(args, dict) else []
    return {"keys": keys, "n_args": len(keys)}


async def evaluate_tool_call(
    *,
    opa_url: str,
    principal_roles: list[str],
    workspace_ids: list[str],
    agent_id: str,
    agent_allowed_tools: list[str],
    tool_id: str,
    tool_name: str,
    tool_scopes: list[str],
    args: dict[str, Any] | None = None,
    timeout: float = 3.0,
) -> Decision:
    payload = {
        "input": {
            "principal": {"roles": principal_roles, "workspace_ids": workspace_ids},
            "agent": {"id": agent_id, "allowed_tools": agent_allowed_tools},
            "tool": {"id": tool_id, "name": tool_name, "scopes": tool_scopes},
            "args_summary": _summarise_args(args or {}),
        }
    }
    pkg = "agenticos/tool_access"
    url = f"{opa_url.rstrip('/')}/v1/data/{pkg}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, json=payload)
    except httpx.HTTPError as exc:
        log.warning("opa_unreachable", error=str(exc))
        env = os.environ.get("AGENTICOS_ENV", "development")
        if env in ("test", "development"):
            d = Decision(True, "opa_offline_dev_default_allow")
        else:
            d = Decision(False, f"opa unreachable: {exc}")
        try:
            record_policy_decision(
                package=pkg,
                decision="allow" if d.allow else "deny",
                reason=d.reason,
            )
        except Exception:
            pass
        return d

    if r.status_code >= 400:
        log.warning("opa_error", status=r.status_code, body=r.text[:200])
        d = Decision(False, f"opa error {r.status_code}")
    else:
        body = r.json() or {}
        result = body.get("result")
        if isinstance(result, dict) and "allow" in result:
            d = Decision(bool(result["allow"]), result.get("reason"))
        else:
            d = Decision(bool(result))

    try:
        record_policy_decision(
            package=pkg,
            decision="allow" if d.allow else "deny",
            reason=d.reason,
        )
    except Exception:
        pass
    return d


# Convenience alias matching the PLAN §5 step name.
async def policy_check(
    *,
    opa_url: str,
    workspace_id: UUID,
    agent_id: UUID,
    agent_allowed_tools: list[str],
    tool_id: str,
    tool_name: str,
    tool_scopes: list[str],
    args: dict[str, Any] | None = None,
    principal_roles: list[str] | None = None,
) -> Decision:
    return await evaluate_tool_call(
        opa_url=opa_url,
        principal_roles=principal_roles or ["builder"],
        workspace_ids=[str(workspace_id)],
        agent_id=str(agent_id),
        agent_allowed_tools=agent_allowed_tools,
        tool_id=tool_id,
        tool_name=tool_name,
        tool_scopes=tool_scopes,
        args=args,
    )
