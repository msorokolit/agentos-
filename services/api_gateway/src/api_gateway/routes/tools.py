"""Tools proxy: workspace-scoped CRUD + invoke."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import httpx
from agenticos_shared.audit import AuditEvent, safe_payload
from agenticos_shared.auth import Principal
from agenticos_shared.errors import AgenticOSError
from agenticos_shared.models import Agent
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit_bus import get_emitter
from ..auth.deps import require_workspace_role
from ..db import get_db
from ..settings import Settings, get_settings

router = APIRouter(tags=["tools"])


async def _proxy(
    method: str, path: str, settings: Settings, *, json: Any | None = None
) -> tuple[int, Any]:
    url = f"{settings.tool_registry_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.request(method, url, json=json)
    if r.status_code >= 400:
        try:
            problem = r.json()
        except Exception:
            problem = {"detail": r.text}
        raise AgenticOSError(
            problem.get("detail") or "tool-registry error",
            status=r.status_code,
            code=problem.get("code") or "tool_error",
            title=problem.get("title") or "Tool error",
        )
    if r.status_code == 204:
        return 204, None
    return r.status_code, r.json()


@router.get("/builtins")
async def list_builtins(settings: Annotated[Settings, Depends(get_settings)]):
    _, body = await _proxy("GET", "/builtins", settings)
    return body


@router.get("/workspaces/{workspace_id}/tools")
async def list_tools(
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("tool:read"))],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _, ws_id = ctx
    _, body = await _proxy("GET", f"/tools?workspace_id={ws_id}", settings)
    return body


@router.post(
    "/workspaces/{workspace_id}/tools",
    status_code=status.HTTP_201_CREATED,
)
async def create_tool(
    body: dict,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("tool:write"))],
    settings: Annotated[Settings, Depends(get_settings)],
):
    principal, ws_id = ctx
    payload = {**body, "workspace_id": str(ws_id)}
    _, out = await _proxy("POST", "/tools", settings, json=payload)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="tool.create",
            resource_type="tool",
            resource_id=str(out.get("id") if isinstance(out, dict) else ""),
            payload=safe_payload({k: v for k, v in body.items() if k != "descriptor"}),
            ip=request.client.host if request.client else None,
        )
    )
    return out


@router.patch("/workspaces/{workspace_id}/tools/{tool_id}")
async def update_tool(
    tool_id: UUID,
    body: dict,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("tool:write"))],
    settings: Annotated[Settings, Depends(get_settings)],
):
    principal, ws_id = ctx
    _, out = await _proxy("PATCH", f"/tools/{tool_id}", settings, json=body)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="tool.update",
            resource_type="tool",
            resource_id=str(tool_id),
            payload=safe_payload(body),
            ip=request.client.host if request.client else None,
        )
    )
    return out


@router.delete(
    "/workspaces/{workspace_id}/tools/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_tool(
    tool_id: UUID,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("tool:write"))],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
):
    principal, ws_id = ctx
    await _proxy("DELETE", f"/tools/{tool_id}", settings)

    # ToolBinding rows are removed by ON DELETE CASCADE in the tool table,
    # but the JSON ``tool_ids`` list on each agent needs explicit pruning.
    affected_agents = db.execute(select(Agent).where(Agent.workspace_id == ws_id)).scalars().all()
    tid = str(tool_id)
    pruned: list[str] = []
    for a in affected_agents:
        if tid in (a.tool_ids or []):
            a.tool_ids = [t for t in a.tool_ids if t != tid]
            pruned.append(str(a.id))

    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="tool.delete",
            resource_type="tool",
            resource_id=str(tool_id),
            payload={"pruned_agents": pruned},
            ip=request.client.host if request.client else None,
        )
    )


@router.post("/workspaces/{workspace_id}/tools/{tool_id}/invoke")
async def invoke_tool(
    tool_id: UUID,
    body: dict,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("tool:read"))],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
):
    """Manual invocation from the UI / SDK (separate from agent-runtime path)."""

    from agenticos_shared.models import Workspace

    principal, ws_id = ctx
    # Workspace-scoped egress allow-list, merged with the gateway's global.
    extra: list[str] = []
    ws = db.get(Workspace, ws_id)
    if ws and isinstance(ws.settings, dict):
        raw = ws.settings.get("egress_allow_hosts") or []
        if isinstance(raw, list):
            extra = [str(h) for h in raw if isinstance(h, str | int)]

    payload = {
        "tool_id": str(tool_id),
        "workspace_id": str(ws_id),
        "args": body.get("args") or {},
        "extra_allow_hosts": extra,
    }
    _, out = await _proxy("POST", "/invoke", settings, json=payload)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="tool.invoke",
            resource_type="tool",
            resource_id=str(tool_id),
            payload={"ok": bool(out.get("ok") if isinstance(out, dict) else False)},
            ip=request.client.host if request.client else None,
        )
    )
    return out
