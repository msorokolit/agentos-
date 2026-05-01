"""Agents CRUD + chat sessions/messages + run.

WS streaming uses ``/chat/{agent_id}/ws`` (in chat.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

import httpx
from agenticos_shared.audit import AuditEvent, safe_payload
from agenticos_shared.auth import Principal
from agenticos_shared.errors import (
    AgenticOSError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from agenticos_shared.models import Agent, AgentVersion, Message, Session, ToolBinding
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from ..audit_bus import get_emitter
from ..auth.deps import current_principal, require_workspace_role
from ..db import get_db
from ..job_queue import enqueue
from ..model_capabilities import ensure_model_supports
from ..settings import Settings, get_settings

router = APIRouter(tags=["agents"])


# ---------------------------------------------------------------------------
# Top-level by-id helpers (PLAN §4: GET/PATCH/DELETE /agents/{id},
# POST /agents/{id}/run). They resolve the workspace from the agent and
# enforce membership inline; cross-tenant ids 404 without leaking
# existence.
# ---------------------------------------------------------------------------
def _resolve_agent_or_404(*, agent_id: UUID, principal: Principal, db: DBSession) -> Agent:
    a = db.get(Agent, agent_id)
    if a is None:
        raise NotFoundError("agent not found")
    if a.workspace_id not in principal.workspace_ids and "superuser" not in principal.roles:
        raise NotFoundError("agent not found")
    return a


def _require_role_for_agent(
    *,
    agent: Agent,
    principal: Principal,
    perm: str,
    db: DBSession,
) -> None:
    """Inline RBAC for the top-level routes that don't have ``workspace_id``
    in the path. Mirrors :func:`require_workspace_role` for the bound
    workspace."""

    from agenticos_shared.errors import ForbiddenError
    from agenticos_shared.models import WorkspaceMember
    from sqlalchemy import select as _select

    from ..auth.deps import PERMISSIONS, ROLE_RANK

    if "superuser" in principal.roles:
        return
    role = db.execute(
        _select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == agent.workspace_id,
            WorkspaceMember.user_id == principal.user_id,
        )
    ).scalar_one_or_none()
    if role is None:
        # Don't differentiate "not a member" from "not found" at this layer.
        raise NotFoundError("agent not found")
    if ROLE_RANK.get(role, -1) < PERMISSIONS[perm]:
        raise ForbiddenError(f"role '{role}' insufficient for '{perm}'")


@router.get("/agents/{agent_id}")
def get_agent_top_level(
    agent_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[DBSession, Depends(get_db)],
):
    """PLAN §4 ``GET /agents/{id}``: by-id lookup that doesn't require
    a workspace_id in the path."""

    a = _resolve_agent_or_404(agent_id=agent_id, principal=principal, db=db)
    _require_role_for_agent(agent=a, principal=principal, perm="agent:read", db=db)
    return _agent_out(a)


@router.patch("/agents/{agent_id}")
async def patch_agent_top_level(
    agent_id: UUID,
    body: dict,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[DBSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """PLAN §4 ``PATCH /agents/{id}``: forwards into the workspace-
    scoped handler so all the capability checks + version snapshots
    + audit emit run identically."""

    a = _resolve_agent_or_404(agent_id=agent_id, principal=principal, db=db)
    _require_role_for_agent(agent=a, principal=principal, perm="agent:write", db=db)
    # Reuse the existing workspace-scoped handler.
    return await update_agent(
        agent_id=agent_id,
        body=body,
        request=request,
        ctx=(principal, a.workspace_id),
        db=db,
        settings=settings,
    )


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_top_level(
    agent_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[DBSession, Depends(get_db)],
):
    a = _resolve_agent_or_404(agent_id=agent_id, principal=principal, db=db)
    _require_role_for_agent(agent=a, principal=principal, perm="agent:delete", db=db)
    return await delete_agent(
        agent_id=agent_id,
        request=request,
        ctx=(principal, a.workspace_id),
        db=db,
    )


@router.post("/agents/{agent_id}/run")
async def run_agent_top_level(
    agent_id: UUID,
    body: dict,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[DBSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """PLAN §4 ``POST /agents/{id}/run``: convenience that doesn't
    require a workspace_id in the path."""

    a = _resolve_agent_or_404(agent_id=agent_id, principal=principal, db=db)
    _require_role_for_agent(agent=a, principal=principal, perm="agent:read", db=db)
    return await run_agent(
        agent_id=agent_id,
        body=body,
        request=request,
        ctx=(principal, a.workspace_id),
        db=db,
        settings=settings,
    )


def _sync_tool_bindings(db: DBSession, *, agent_id: UUID, tool_ids: list[str]) -> None:
    """Make ``tool_binding`` rows match the agent's ``tool_ids`` list."""

    desired: set[UUID] = set()
    for raw in tool_ids or []:
        try:
            desired.add(UUID(str(raw)))
        except ValueError:
            continue

    existing_rows = (
        db.execute(select(ToolBinding).where(ToolBinding.agent_id == agent_id)).scalars().all()
    )
    existing = {b.tool_id: b for b in existing_rows}

    # Add new ones.
    for tid in desired - set(existing):
        db.add(ToolBinding(agent_id=agent_id, tool_id=tid))
    # Drop removed ones.
    for tid, row in existing.items():
        if tid not in desired:
            db.delete(row)


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------
def _agent_out(a: Agent) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "workspace_id": str(a.workspace_id),
        "name": a.name,
        "slug": a.slug,
        "description": a.description,
        "system_prompt": a.system_prompt,
        "model_alias": a.model_alias,
        "graph_kind": a.graph_kind,
        "config": dict(a.config or {}),
        "tool_ids": list(a.tool_ids or []),
        "rag_collection_id": str(a.rag_collection_id) if a.rag_collection_id else None,
        "version": a.version,
        "enabled": a.enabled,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


@router.get("/workspaces/{workspace_id}/agents")
def list_agents(
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:read"))],
    db: Annotated[DBSession, Depends(get_db)],
):
    _, ws_id = ctx
    rows = (
        db.execute(select(Agent).where(Agent.workspace_id == ws_id).order_by(Agent.name))
        .scalars()
        .all()
    )
    return [_agent_out(a) for a in rows]


@router.post(
    "/workspaces/{workspace_id}/agents",
    status_code=status.HTTP_201_CREATED,
)
async def create_agent(
    body: dict,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:write"))],
    db: Annotated[DBSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    principal, ws_id = ctx
    await ensure_model_supports(
        alias=body.get("model_alias", "chat-default"),
        needs_tool_use=bool(body.get("tool_ids")),
        needs_rag=bool(
            body.get("rag_collection_id") or (body.get("config") or {}).get("rag_enabled")
        ),
        settings=settings,
    )
    a = Agent(
        id=uuid4(),
        workspace_id=ws_id,
        name=body.get("name", "untitled"),
        slug=body["slug"],
        description=body.get("description"),
        system_prompt=body.get("system_prompt", ""),
        model_alias=body.get("model_alias", "chat-default"),
        graph_kind=body.get("graph_kind", "react"),
        config=body.get("config", {}),
        tool_ids=body.get("tool_ids", []),
        rag_collection_id=UUID(body["rag_collection_id"])
        if body.get("rag_collection_id")
        else None,
        created_by=principal.user_id,
    )
    db.add(a)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"agent slug '{a.slug}' already exists") from exc

    # Mirror tool_ids into the join table for referential integrity.
    _sync_tool_bindings(db, agent_id=a.id, tool_ids=list(a.tool_ids or []))

    # First immutable snapshot.
    db.add(
        AgentVersion(
            id=uuid4(),
            agent_id=a.id,
            version=a.version,
            created_by=principal.user_id,
            snapshot=_agent_out(a),
        )
    )

    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="agent.create",
            resource_type="agent",
            resource_id=str(a.id),
            payload=safe_payload({k: v for k, v in body.items() if k != "system_prompt"}),
            ip=request.client.host if request.client else None,
        )
    )
    return _agent_out(a)


@router.patch("/workspaces/{workspace_id}/agents/{agent_id}")
async def update_agent(
    agent_id: UUID,
    body: dict,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:write"))],
    db: Annotated[DBSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    principal, ws_id = ctx
    a = db.get(Agent, agent_id)
    if a is None or a.workspace_id != ws_id:
        raise NotFoundError("agent not found")

    # Re-validate capabilities for the post-update state.
    new_alias = body.get("model_alias", a.model_alias)
    new_tool_ids = body.get("tool_ids", a.tool_ids)
    new_config = body.get("config", a.config) or {}
    new_rag = body.get("rag_collection_id", a.rag_collection_id) or new_config.get("rag_enabled")
    await ensure_model_supports(
        alias=new_alias,
        needs_tool_use=bool(new_tool_ids),
        needs_rag=bool(new_rag),
        settings=settings,
    )

    for k in (
        "name",
        "description",
        "system_prompt",
        "model_alias",
        "graph_kind",
        "config",
        "tool_ids",
        "enabled",
    ):
        if k in body and body[k] is not None:
            setattr(a, k, body[k])
    if "rag_collection_id" in body:
        a.rag_collection_id = UUID(body["rag_collection_id"]) if body["rag_collection_id"] else None
    a.version = a.version + 1
    a.updated_at = datetime.now(tz=UTC)

    # Re-sync the join table when tool_ids changed.
    if "tool_ids" in body:
        _sync_tool_bindings(db, agent_id=a.id, tool_ids=list(a.tool_ids or []))

    # Immutable snapshot of the new version.
    db.add(
        AgentVersion(
            id=uuid4(),
            agent_id=a.id,
            version=a.version,
            created_by=principal.user_id,
            snapshot=_agent_out(a),
        )
    )

    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="agent.update",
            resource_type="agent",
            resource_id=str(agent_id),
            payload=safe_payload({k: v for k, v in body.items() if k != "system_prompt"}),
            request_id=principal.request_id,
        )
    )
    return _agent_out(a)


@router.delete(
    "/workspaces/{workspace_id}/agents/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_agent(
    agent_id: UUID,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:delete"))],
    db: Annotated[DBSession, Depends(get_db)],
):
    principal, ws_id = ctx
    a = db.get(Agent, agent_id)
    if a is None or a.workspace_id != ws_id:
        raise NotFoundError("agent not found")
    db.delete(a)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="agent.delete",
            resource_type="agent",
            resource_id=str(agent_id),
        )
    )


@router.post(
    "/workspaces/{workspace_id}/agents/{agent_id}/versions",
    status_code=status.HTTP_201_CREATED,
)
async def publish_agent_version(
    agent_id: UUID,
    body: dict,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:write"))],
    db: Annotated[DBSession, Depends(get_db)],
):
    """Explicitly publish a new immutable version of an agent.

    Snapshots the *current* agent state under a fresh version number and
    records optional release notes in ``snapshot.notes``. Useful when an
    operator wants a stable cut-line independent of the auto-bump that
    happens on every PATCH.
    """

    principal, ws_id = ctx
    a = db.get(Agent, agent_id)
    if a is None or a.workspace_id != ws_id:
        raise NotFoundError("agent not found")

    a.version = a.version + 1
    a.updated_at = datetime.now(tz=UTC)

    snapshot = _agent_out(a)
    notes = (body or {}).get("notes")
    if notes:
        snapshot["notes"] = str(notes)[:4096]
    version = AgentVersion(
        id=uuid4(),
        agent_id=a.id,
        version=a.version,
        created_by=principal.user_id,
        snapshot=snapshot,
    )
    db.add(version)

    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="agent.publish",
            resource_type="agent",
            resource_id=str(agent_id),
            payload={"version": a.version, "notes": bool(notes)},
            ip=request.client.host if request.client else None,
        )
    )
    return {
        "id": str(version.id),
        "agent_id": str(a.id),
        "version": a.version,
        "snapshot": snapshot,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


@router.post(
    "/workspaces/{workspace_id}/agents/{agent_id}/tools/{tool_id}",
    status_code=status.HTTP_201_CREATED,
)
async def bind_agent_tool(
    agent_id: UUID,
    tool_id: UUID,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:write"))],
    db: Annotated[DBSession, Depends(get_db)],
):
    """Bind a tool to an agent (PLAN §4 ``POST /agents/{id}/tools``)."""

    principal, ws_id = ctx
    a = db.get(Agent, agent_id)
    if a is None or a.workspace_id != ws_id:
        raise NotFoundError("agent not found")

    # Verify the tool exists in this workspace (or is global) by hitting
    # the join-table FK: we just insert if absent.
    tids = list(a.tool_ids or [])
    tid_str = str(tool_id)
    if tid_str not in tids:
        tids.append(tid_str)
    a.tool_ids = tids
    a.version = a.version + 1
    a.updated_at = datetime.now(tz=UTC)
    try:
        _sync_tool_bindings(db, agent_id=a.id, tool_ids=tids)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise NotFoundError(f"tool '{tool_id}' not found") from exc

    db.add(
        AgentVersion(
            id=uuid4(),
            agent_id=a.id,
            version=a.version,
            created_by=principal.user_id,
            snapshot=_agent_out(a),
        )
    )
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="agent.tool.bind",
            resource_type="agent",
            resource_id=str(agent_id),
            payload={"tool_id": tid_str},
            ip=request.client.host if request.client else None,
        )
    )
    return _agent_out(a)


@router.delete(
    "/workspaces/{workspace_id}/agents/{agent_id}/tools/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unbind_agent_tool(
    agent_id: UUID,
    tool_id: UUID,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:write"))],
    db: Annotated[DBSession, Depends(get_db)],
):
    principal, ws_id = ctx
    a = db.get(Agent, agent_id)
    if a is None or a.workspace_id != ws_id:
        raise NotFoundError("agent not found")

    tid_str = str(tool_id)
    tids = list(a.tool_ids or [])
    if tid_str not in tids:
        raise NotFoundError("tool not bound to this agent")
    tids = [t for t in tids if t != tid_str]
    a.tool_ids = tids
    a.version = a.version + 1
    a.updated_at = datetime.now(tz=UTC)
    _sync_tool_bindings(db, agent_id=a.id, tool_ids=tids)

    db.add(
        AgentVersion(
            id=uuid4(),
            agent_id=a.id,
            version=a.version,
            created_by=principal.user_id,
            snapshot=_agent_out(a),
        )
    )
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="agent.tool.unbind",
            resource_type="agent",
            resource_id=str(agent_id),
            payload={"tool_id": tid_str},
            ip=request.client.host if request.client else None,
        )
    )


@router.get("/workspaces/{workspace_id}/agents/{agent_id}/versions")
def list_agent_versions(
    agent_id: UUID,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:read"))],
    db: Annotated[DBSession, Depends(get_db)],
):
    _, ws_id = ctx
    a = db.get(Agent, agent_id)
    if a is None or a.workspace_id != ws_id:
        raise NotFoundError("agent not found")
    rows = (
        db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "agent_id": str(r.agent_id),
            "version": r.version,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "created_by": str(r.created_by) if r.created_by else None,
            "snapshot": dict(r.snapshot or {}),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Sessions + messages
# ---------------------------------------------------------------------------
@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session_top_level(
    body: dict,
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[DBSession, Depends(get_db)],
):
    """Convenience top-level session creator (PLAN §4: ``POST /sessions``).

    Body: ``{"agent_id": "<uuid>", "title": "..."?}``.
    Resolves the workspace from the agent and enforces ``agent:read`` on
    that workspace inline (since the path doesn't carry a workspace_id).
    """

    agent_id_raw = (body or {}).get("agent_id")
    if not agent_id_raw:
        raise ValidationError("agent_id is required")
    try:
        agent_id = UUID(str(agent_id_raw))
    except ValueError as exc:
        raise ValidationError(f"agent_id must be a UUID: {exc}") from exc

    a = db.get(Agent, agent_id)
    if a is None:
        raise NotFoundError("agent not found")
    if a.workspace_id not in principal.workspace_ids and "superuser" not in principal.roles:
        raise NotFoundError("agent not found")  # don't leak existence

    s = Session(
        id=uuid4(),
        workspace_id=a.workspace_id,
        agent_id=agent_id,
        user_id=principal.user_id,
        title=body.get("title") if isinstance(body, dict) else None,
        meta={},
    )
    db.add(s)
    db.flush()
    return {
        "id": str(s.id),
        "agent_id": str(agent_id),
        "workspace_id": str(a.workspace_id),
        "title": s.title,
        "created_at": s.created_at.isoformat(),
    }


@router.post(
    "/workspaces/{workspace_id}/agents/{agent_id}/sessions",
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    agent_id: UUID,
    body: dict,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:read"))],
    db: Annotated[DBSession, Depends(get_db)],
):
    principal, ws_id = ctx
    a = db.get(Agent, agent_id)
    if a is None or a.workspace_id != ws_id:
        raise NotFoundError("agent not found")
    s = Session(
        id=uuid4(),
        workspace_id=ws_id,
        agent_id=agent_id,
        user_id=principal.user_id,
        title=body.get("title"),
        meta={},
    )
    db.add(s)
    db.flush()
    return {
        "id": str(s.id),
        "agent_id": str(agent_id),
        "workspace_id": str(ws_id),
        "title": s.title,
        "created_at": s.created_at.isoformat(),
    }


@router.get("/sessions/{session_id}/messages")
def list_session_messages_top_level(
    session_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[DBSession, Depends(get_db)],
):
    """Convenience top-level endpoint (PLAN §4 ``GET /sessions/{id}/messages``).

    Resolves the workspace from the session and enforces ``agent:read``
    on it inline (path doesn't carry workspace_id). 404s cleanly across
    tenants without leaking existence.
    """

    s = db.get(Session, session_id)
    if s is None:
        raise NotFoundError("session not found")
    if s.workspace_id not in principal.workspace_ids and "superuser" not in principal.roles:
        raise NotFoundError("session not found")

    rows = (
        db.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "tool_call": m.tool_call,
            "citations": list(m.citations or []),
            "tokens_in": m.tokens_in,
            "tokens_out": m.tokens_out,
            "latency_ms": m.latency_ms,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


@router.get(
    "/workspaces/{workspace_id}/sessions/{session_id}/messages",
)
def list_session_messages(
    session_id: UUID,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:read"))],
    db: Annotated[DBSession, Depends(get_db)],
):
    _, ws_id = ctx
    s = db.get(Session, session_id)
    if s is None or s.workspace_id != ws_id:
        raise NotFoundError("session not found")
    rows = (
        db.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "tool_call": m.tool_call,
            "citations": list(m.citations or []),
            "tokens_in": m.tokens_in,
            "tokens_out": m.tokens_out,
            "latency_ms": m.latency_ms,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


@router.post("/workspaces/{workspace_id}/sessions/{session_id}/end")
async def end_session(
    session_id: UUID,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:read"))],
    db: Annotated[DBSession, Depends(get_db)],
):
    """Mark a chat session ended and enqueue summarisation."""

    principal, ws_id = ctx
    s = db.get(Session, session_id)
    if s is None or s.workspace_id != ws_id:
        raise NotFoundError("session not found")
    if s.ended_at is None:
        s.ended_at = datetime.now(tz=UTC)
    job_id = await enqueue("summarize_session", str(session_id))
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="session.end",
            resource_type="session",
            resource_id=str(session_id),
            payload={"job_id": job_id, "queued": job_id is not None},
            ip=request.client.host if request.client else None,
        )
    )
    return {"session_id": str(session_id), "job_id": job_id, "queued": job_id is not None}


# ---------------------------------------------------------------------------
# Run (synchronous; the WS endpoint uses /run/stream)
# ---------------------------------------------------------------------------
async def _proxy_runtime(method: str, path: str, settings: Settings, *, json: Any | None = None):
    url = f"{settings.agent_runtime_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=300.0) as c:
        r = await c.request(method, url, json=json)
    if r.status_code >= 400:
        try:
            problem = r.json()
        except Exception:
            problem = {"detail": r.text}
        raise AgenticOSError(
            problem.get("detail") or "agent-runtime error",
            status=r.status_code,
            code=problem.get("code") or "agent_runtime_error",
            title=problem.get("title") or "Agent runtime error",
        )
    return r.json()


@router.post("/workspaces/{workspace_id}/agents/{agent_id}/run")
async def run_agent(
    agent_id: UUID,
    body: dict,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:read"))],
    db: Annotated[DBSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    principal, ws_id = ctx
    a = db.get(Agent, agent_id)
    if a is None or a.workspace_id != ws_id:
        raise NotFoundError("agent not found")

    session_id = body.get("session_id")
    if session_id is None:
        s = Session(
            id=uuid4(),
            workspace_id=ws_id,
            agent_id=agent_id,
            user_id=principal.user_id,
            meta={},
        )
        db.add(s)
        db.commit()
        session_id = s.id
    else:
        session_id = UUID(session_id)
        s = db.get(Session, session_id)
        if s is None:
            raise NotFoundError("session not found")

    payload = {
        "agent_id": str(agent_id),
        "session_id": str(session_id),
        "user_message": body.get("user_message", ""),
    }
    out = await _proxy_runtime("POST", "/run", settings, json=payload)
    out["session_id"] = str(session_id)

    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="agent.run",
            resource_type="agent",
            resource_id=str(agent_id),
            payload={
                "session_id": str(session_id),
                "iterations": out.get("iterations"),
                "tool_calls": len(out.get("tool_calls") or []),
                "error": out.get("error"),
            },
            ip=request.client.host if request.client else None,
        )
    )
    return out


# ---------------------------------------------------------------------------
# Streaming run (SSE) — passthrough to agent-runtime /run/stream
# ---------------------------------------------------------------------------
from fastapi.responses import StreamingResponse  # noqa: E402


@router.post("/workspaces/{workspace_id}/agents/{agent_id}/run/stream")
async def run_agent_stream(
    agent_id: UUID,
    body: dict,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("agent:read"))],
    db: Annotated[DBSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    principal, ws_id = ctx
    a = db.get(Agent, agent_id)
    if a is None or a.workspace_id != ws_id:
        raise NotFoundError("agent not found")

    # Resolve / create the session.
    session_id = body.get("session_id")
    if session_id is None:
        s = Session(
            id=uuid4(),
            workspace_id=ws_id,
            agent_id=agent_id,
            user_id=principal.user_id,
            meta={},
        )
        db.add(s)
        db.commit()
        session_id = s.id
    else:
        session_id = UUID(session_id)
        if db.get(Session, session_id) is None:
            raise NotFoundError("session not found")

    payload = {
        "agent_id": str(agent_id),
        "session_id": str(session_id),
        "user_message": body.get("user_message", ""),
    }

    async def _gen():
        async with (
            httpx.AsyncClient(timeout=600.0) as c,
            c.stream(
                "POST",
                f"{settings.agent_runtime_url.rstrip('/')}/run/stream",
                json=payload,
            ) as r,
        ):
            async for line in r.aiter_lines():
                if line:
                    yield (line + "\n\n").encode()

    return StreamingResponse(_gen(), media_type="text/event-stream")
