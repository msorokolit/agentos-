"""Workspace + member management routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from agenticos_shared.audit import AuditEvent, safe_payload
from agenticos_shared.auth import Principal
from agenticos_shared.errors import ConflictError, ForbiddenError, NotFoundError
from agenticos_shared.models import User, Workspace, WorkspaceMember
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit_bus import get_emitter
from ..auth.deps import current_principal, require_workspace_role
from ..db import get_db
from ..schemas import (
    MemberAdd,
    MemberOut,
    MemberUpdate,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ---------------------------------------------------------------------------
# Workspace CRUD
# ---------------------------------------------------------------------------
@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceOut]:
    if "superuser" in principal.roles:
        rows = (
            db.execute(select(Workspace).where(Workspace.tenant_id == principal.tenant_id))
            .scalars()
            .all()
        )
    else:
        rows = (
            db.execute(
                select(Workspace)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                .where(
                    Workspace.tenant_id == principal.tenant_id,
                    WorkspaceMember.user_id == principal.user_id,
                )
            )
            .scalars()
            .all()
        )
    return [
        WorkspaceOut(
            id=w.id,
            tenant_id=w.tenant_id,
            name=w.name,
            slug=w.slug,
            created_at=w.created_at,
        )
        for w in rows
    ]


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceOut:
    # Any authenticated user may create a workspace; they become its owner.
    ws = Workspace(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        name=body.name,
        slug=body.slug,
    )
    db.add(ws)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"workspace slug '{body.slug}' already exists") from exc
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=principal.user_id, role="owner"))

    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws.id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="workspace.create",
            resource_type="workspace",
            resource_id=str(ws.id),
            payload=safe_payload({"slug": body.slug, "name": body.name}),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            request_id=principal.request_id,
        )
    )
    return WorkspaceOut(
        id=ws.id,
        tenant_id=ws.tenant_id,
        name=ws.name,
        slug=ws.slug,
        created_at=ws.created_at,
    )


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("workspace:read"))],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceOut:
    _, ws_id = ctx
    ws = db.get(Workspace, ws_id)
    assert ws is not None  # guarded by dependency
    return WorkspaceOut(
        id=ws.id,
        tenant_id=ws.tenant_id,
        name=ws.name,
        slug=ws.slug,
        created_at=ws.created_at,
    )


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    body: WorkspaceUpdate,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("workspace:write"))],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceOut:
    principal, ws_id = ctx
    ws = db.get(Workspace, ws_id)
    assert ws is not None
    if body.name is not None:
        ws.name = body.name

    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws.id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="workspace.update",
            resource_type="workspace",
            resource_id=str(ws.id),
            payload=safe_payload(body.model_dump(exclude_none=True)),
            ip=request.client.host if request.client else None,
            request_id=principal.request_id,
        )
    )
    return WorkspaceOut(
        id=ws.id,
        tenant_id=ws.tenant_id,
        name=ws.name,
        slug=ws.slug,
        created_at=ws.created_at,
    )


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("workspace:delete"))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    principal, ws_id = ctx
    ws = db.get(Workspace, ws_id)
    assert ws is not None
    db.delete(ws)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="workspace.delete",
            resource_type="workspace",
            resource_id=str(ws_id),
            ip=request.client.host if request.client else None,
            request_id=principal.request_id,
        )
    )


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
@router.get("/{workspace_id}/members", response_model=list[MemberOut])
def list_members(
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("member:read"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[MemberOut]:
    _, ws_id = ctx
    rows = db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == ws_id)
        .order_by(User.email)
    ).all()
    return [
        MemberOut(
            user_id=m.user_id,
            email=u.email,
            display_name=u.display_name,
            role=m.role,  # type: ignore[arg-type]
            added_at=m.created_at,
        )
        for m, u in rows
    ]


@router.post(
    "/{workspace_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    body: MemberAdd,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("member:write"))],
    db: Annotated[Session, Depends(get_db)],
) -> MemberOut:
    principal, ws_id = ctx
    user = db.execute(
        select(User).where(
            User.tenant_id == principal.tenant_id,
            User.email == body.email,
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError(f"user '{body.email}' not found in tenant")

    existing = db.get(WorkspaceMember, (ws_id, user.id))
    if existing is not None:
        raise ConflictError("user is already a member of this workspace")

    if (
        body.role == "owner"
        and "owner" not in principal.roles
        and "superuser" not in principal.roles
    ):
        raise ForbiddenError("only owners may add another owner")

    m = WorkspaceMember(workspace_id=ws_id, user_id=user.id, role=body.role)
    db.add(m)
    db.flush()

    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="member.add",
            resource_type="member",
            resource_id=str(user.id),
            payload={"email": body.email, "role": body.role},
            ip=request.client.host if request.client else None,
            request_id=principal.request_id,
        )
    )
    return MemberOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=m.role,  # type: ignore[arg-type]
        added_at=m.created_at,
    )


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberOut)
async def update_member(
    user_id: UUID,
    body: MemberUpdate,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("member:write"))],
    db: Annotated[Session, Depends(get_db)],
) -> MemberOut:
    principal, ws_id = ctx
    m = db.get(WorkspaceMember, (ws_id, user_id))
    if m is None:
        raise NotFoundError("member not found")
    user = db.get(User, user_id)
    assert user is not None

    if (
        (m.role == "owner" or body.role == "owner")
        and "owner" not in principal.roles
        and "superuser" not in principal.roles
    ):
        raise ForbiddenError("only owners may change owner roles")

    m.role = body.role
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="member.update",
            resource_type="member",
            resource_id=str(user_id),
            payload={"role": body.role},
            ip=request.client.host if request.client else None,
            request_id=principal.request_id,
        )
    )
    return MemberOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=m.role,  # type: ignore[arg-type]
        added_at=m.created_at,
    )


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: UUID,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("member:write"))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    principal, ws_id = ctx
    m = db.get(WorkspaceMember, (ws_id, user_id))
    if m is None:
        raise NotFoundError("member not found")

    if m.role == "owner":
        # Don't let the last owner be removed.
        owner_count = db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws_id,
                WorkspaceMember.role == "owner",
            )
        ).all()
        if len(owner_count) <= 1:
            raise ForbiddenError("cannot remove the last owner of a workspace")

    db.delete(m)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="member.remove",
            resource_type="member",
            resource_id=str(user_id),
            ip=request.client.host if request.client else None,
            request_id=principal.request_id,
        )
    )
