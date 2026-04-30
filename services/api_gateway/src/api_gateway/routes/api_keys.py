"""Workspace-scoped API keys.

* Caller must have ``admin`` in the workspace.
* On create we return the **plaintext** exactly once; the DB only stores
  ``sha256(token)``.
* List/delete operate on the hashed prefix; revoking sets ``revoked_at``
  (the row is preserved for audit-trail correlation).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from agenticos_shared.audit import AuditEvent
from agenticos_shared.auth import Principal
from agenticos_shared.errors import NotFoundError
from agenticos_shared.models import ApiKey
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit_bus import get_emitter
from ..auth.api_keys import mint_token
from ..auth.deps import require_workspace_role
from ..db import get_db

router = APIRouter(tags=["api-keys"])


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=lambda: ["read", "write"])
    ttl_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyOut(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    """Returned only on creation: includes the **plaintext** token."""

    token: str


def _to_out(row: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        prefix=row.prefix,
        scopes=list(row.scopes or []),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


@router.get("/workspaces/{workspace_id}/api-keys", response_model=list[ApiKeyOut])
def list_keys(
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("admin:read"))],
    db: Annotated[Session, Depends(get_db)],
) -> list[ApiKeyOut]:
    _, ws_id = ctx
    rows = (
        db.execute(
            select(ApiKey).where(ApiKey.workspace_id == ws_id).order_by(ApiKey.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_to_out(r) for r in rows]


@router.post(
    "/workspaces/{workspace_id}/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_key(
    body: ApiKeyCreate,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("admin:write"))],
    db: Annotated[Session, Depends(get_db)],
) -> ApiKeyCreated:
    principal, ws_id = ctx
    plaintext, prefix, digest = mint_token()
    expires_at = datetime.now(tz=UTC) + timedelta(days=body.ttl_days) if body.ttl_days else None
    row = ApiKey(
        id=uuid4(),
        workspace_id=ws_id,
        name=body.name,
        prefix=prefix,
        hashed_key=digest,
        scopes=body.scopes,
        created_by=principal.user_id,
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()

    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="api_key.create",
            resource_type="api_key",
            resource_id=str(row.id),
            payload={"name": body.name, "prefix": prefix, "scopes": body.scopes},
            ip=request.client.host if request.client else None,
        )
    )
    out = _to_out(row).model_dump()
    out["token"] = plaintext
    return ApiKeyCreated.model_validate(out)


@router.delete(
    "/workspaces/{workspace_id}/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_key(
    key_id: UUID,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("admin:write"))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    principal, ws_id = ctx
    row = db.get(ApiKey, key_id)
    if row is None or row.workspace_id != ws_id:
        raise NotFoundError("api key not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(tz=UTC)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="api_key.revoke",
            resource_type="api_key",
            resource_id=str(key_id),
            payload={"prefix": row.prefix},
            ip=request.client.host if request.client else None,
        )
    )
