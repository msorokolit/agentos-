"""``GET /me`` — info about the calling user."""

from __future__ import annotations

from typing import Annotated

from agenticos_shared.auth import Principal
from agenticos_shared.models import User, Workspace, WorkspaceMember
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import current_principal
from ..db import get_db
from ..schemas import MeResponse, WorkspaceMembership

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
def me(
    principal: Annotated[Principal, Depends(current_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> MeResponse:
    user = db.get(User, principal.user_id)
    rows = db.execute(
        select(WorkspaceMember.role, Workspace.id, Workspace.name, Workspace.slug)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == principal.user_id)
        .order_by(Workspace.name)
    ).all()

    memberships = [
        WorkspaceMembership(
            workspace_id=ws_id,
            workspace_slug=ws_slug,
            workspace_name=ws_name,
            role=role,  # type: ignore[arg-type]
        )
        for role, ws_id, ws_name, ws_slug in rows
    ]

    return MeResponse(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        email=principal.email,
        display_name=user.display_name if user else principal.display_name,
        is_superuser=user.is_superuser if user else False,
        workspaces=memberships,
    )
