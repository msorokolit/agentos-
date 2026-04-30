"""Dispatch a tool invocation to the right adapter."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import jsonschema
from agenticos_shared.errors import NotFoundError, ValidationError
from agenticos_shared.logging import get_logger
from agenticos_shared.metrics import record_tool_invocation
from agenticos_shared.models import ToolRow
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .builtins import BUILTINS
from .http_plugin import invoke_http, invoke_openapi
from .mcp_client import MCPClient

log = get_logger(__name__)


async def invoke_tool(
    db: Session,
    *,
    tool_id: UUID | None,
    name: str | None,
    workspace_id: UUID,
    args: dict[str, Any],
    settings: Any,
) -> dict[str, Any]:
    """Resolve a tool by id or name+workspace, validate args, invoke."""

    q = select(ToolRow).where(
        or_(ToolRow.workspace_id == workspace_id, ToolRow.workspace_id.is_(None))
    )
    if tool_id is not None:
        q = q.where(ToolRow.id == tool_id)
    elif name is not None:
        q = q.where(ToolRow.name == name)
    else:
        raise ValidationError("must provide tool_id or name")

    row = db.execute(q.order_by(ToolRow.workspace_id.desc())).scalars().first()
    if row is None:
        raise NotFoundError("tool not found")
    if not row.enabled:
        raise ValidationError(f"tool '{row.name}' is disabled")

    descriptor = dict(row.descriptor or {})
    params_schema = descriptor.get("parameters")
    if params_schema:
        try:
            jsonschema.validate(args, params_schema)
        except jsonschema.ValidationError as exc:
            raise ValidationError(f"args invalid: {exc.message}") from exc

    ctx: dict[str, Any] = {"settings": settings, "workspace_id": workspace_id}

    t0 = time.monotonic()
    try:
        if row.kind == "builtin":
            fn = BUILTINS.get(row.name)
            if fn is None:
                raise NotFoundError(f"no built-in named '{row.name}'")
            result = await fn(ctx, args)
        elif row.kind == "http":
            result = await invoke_http(descriptor, ctx=ctx, args=args)
        elif row.kind == "openapi":
            result = await invoke_openapi(descriptor, ctx=ctx, args=args)
        elif row.kind == "mcp":
            client = MCPClient(
                endpoint=descriptor["endpoint"],
                headers=descriptor.get("headers"),
            )
            mcp_result = await client.call_tool(row.name, args)
            result = mcp_result
        else:
            raise ValidationError(f"unknown tool kind: {row.kind}")
    except Exception as exc:
        latency = int((time.monotonic() - t0) * 1000)
        record_tool_invocation(tool=row.name, kind=row.kind, ok=False, latency_ms=latency)
        return {
            "ok": False,
            "error": str(exc)[:1024],
            "latency_ms": latency,
            "tool_id": str(row.id),
            "tool_name": row.name,
            "kind": row.kind,
            "scopes": list(row.scopes or []),
        }

    latency = int((time.monotonic() - t0) * 1000)
    record_tool_invocation(tool=row.name, kind=row.kind, ok=True, latency_ms=latency)
    return {
        "ok": True,
        "result": result,
        "latency_ms": latency,
        "tool_id": str(row.id),
        "tool_name": row.name,
        "kind": row.kind,
        "scopes": list(row.scopes or []),
    }
