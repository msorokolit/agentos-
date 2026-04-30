"""HTTP API for the tool registry."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID, uuid4

from agenticos_shared.db import get_sessionmaker
from agenticos_shared.errors import ConflictError, NotFoundError
from agenticos_shared.models import ToolRow
from agenticos_shared.secrets_box import encrypt_sensitive_fields
from fastapi import APIRouter, Depends, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .builtins import builtin_descriptors
from .invoker import invoke_tool
from .schemas import (
    ToolCreate,
    ToolInvokeRequest,
    ToolInvokeResponse,
    ToolOut,
    ToolUpdate,
)
from .settings import Settings, get_settings

router = APIRouter(tags=["tools"])


def get_db() -> Iterator[Session]:
    sm = get_sessionmaker()
    db = sm()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _row_to_out(row: ToolRow) -> ToolOut:
    return ToolOut(
        id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        display_name=row.display_name,
        description=row.description,
        kind=row.kind,
        descriptor=dict(row.descriptor or {}),
        scopes=list(row.scopes or []),
        enabled=row.enabled,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
@router.get("/builtins", response_model=list[dict])
def list_builtins() -> list[dict]:
    return builtin_descriptors()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("/tools", response_model=list[ToolOut])
def list_tools(
    db: Annotated[Session, Depends(get_db)],
    workspace_id: UUID | None = None,
) -> list[ToolOut]:
    q = select(ToolRow).order_by(ToolRow.name)
    if workspace_id is not None:
        q = q.where(or_(ToolRow.workspace_id == workspace_id, ToolRow.workspace_id.is_(None)))
    return [_row_to_out(r) for r in db.execute(q).scalars().all()]


@router.post("/tools", response_model=ToolOut, status_code=status.HTTP_201_CREATED)
def create_tool(
    body: ToolCreate,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ToolOut:
    descriptor = encrypt_sensitive_fields(body.descriptor, key_material=settings.secret_key)
    row = ToolRow(
        id=uuid4(),
        workspace_id=body.workspace_id,
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        kind=body.kind,
        descriptor=descriptor,
        scopes=body.scopes,
        enabled=True,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"tool '{body.name}' already exists in workspace") from exc
    return _row_to_out(row)


@router.patch("/tools/{tool_id}", response_model=ToolOut)
def update_tool(
    tool_id: UUID,
    body: ToolUpdate,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ToolOut:
    row = db.get(ToolRow, tool_id)
    if row is None:
        raise NotFoundError("tool not found")
    fields = body.model_dump(exclude_none=True)
    if "descriptor" in fields:
        fields["descriptor"] = encrypt_sensitive_fields(
            fields["descriptor"], key_material=settings.secret_key
        )
    for k, v in fields.items():
        setattr(row, k, v)
    db.flush()
    return _row_to_out(row)


@router.delete("/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool(tool_id: UUID, db: Annotated[Session, Depends(get_db)]) -> None:
    row = db.get(ToolRow, tool_id)
    if row is None:
        raise NotFoundError("tool not found")
    db.delete(row)


# ---------------------------------------------------------------------------
# Invocation (used by agent-runtime)
# ---------------------------------------------------------------------------
@router.post("/invoke", response_model=ToolInvokeResponse)
async def invoke(
    body: ToolInvokeRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ToolInvokeResponse:
    out = await invoke_tool(
        db,
        tool_id=body.tool_id,
        name=body.name,
        workspace_id=body.workspace_id,
        args=body.args,
        settings=settings,
        extra_allow_hosts=body.extra_allow_hosts,
    )
    return ToolInvokeResponse(
        ok=bool(out.get("ok", False)),
        result=out.get("result"),
        error=out.get("error"),
        latency_ms=int(out.get("latency_ms", 0)),
    )
