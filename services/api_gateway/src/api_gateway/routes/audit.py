"""Audit log explorer.

Workspace-scoped, paginated, filterable. Visible to admins.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from agenticos_shared.audit_chain import verify_chain
from agenticos_shared.auth import Principal
from agenticos_shared.models import AuditEventRow
from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session as DBSession

from ..auth.deps import require_admin, require_workspace_role
from ..db import get_db

router = APIRouter(tags=["audit"])


@router.get("/workspaces/{workspace_id}/audit")
def list_audit(
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("admin:read"))],
    db: Annotated[DBSession, Depends(get_db)],
    actor: str | None = None,
    action: str | None = None,
    decision: str | None = None,
    # PLAN §4 spells these as ``from`` / ``to``; ``since`` / ``until``
    # are kept as backwards-compatible aliases for clients already on
    # those names.
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query(alias="to")] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    _, ws_id = ctx
    q = (
        select(AuditEventRow)
        .where(AuditEventRow.workspace_id == ws_id)
        .order_by(desc(AuditEventRow.created_at))
        .limit(limit)
        .offset(offset)
    )
    if actor:
        q = q.where(AuditEventRow.actor_email.ilike(f"%{actor}%"))
    if action:
        q = q.where(AuditEventRow.action == action)
    if decision:
        q = q.where(AuditEventRow.decision == decision)
    lower = from_ or since
    upper = to or until
    if lower:
        q = q.where(AuditEventRow.created_at >= lower)
    if upper:
        q = q.where(AuditEventRow.created_at <= upper)

    rows = db.execute(q).scalars().all()
    return _serialise_rows(rows)


def _serialise_rows(rows: list[AuditEventRow]) -> list[dict]:
    return [
        {
            "id": str(r.id),
            "tenant_id": str(r.tenant_id) if r.tenant_id else None,
            "workspace_id": str(r.workspace_id) if r.workspace_id else None,
            "actor_id": str(r.actor_id) if r.actor_id else None,
            "actor_email": r.actor_email,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "decision": r.decision,
            "reason": r.reason,
            "ip": r.ip,
            "request_id": r.request_id,
            "payload": dict(r.payload or {}),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "prev_hash": r.prev_hash,
            "event_hash": r.event_hash,
        }
        for r in rows
    ]


@router.get("/admin/audit/verify")
def verify_audit_chain(
    _principal: Annotated[Principal, Depends(require_admin)],
    db: Annotated[DBSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100_000)] = 10_000,
) -> dict:
    """Walk the audit-event hash chain and report tamper status.

    Reads up to ``limit`` rows in chronological order and recomputes
    each ``event_hash`` from the row's canonical fields plus the
    previous row's stored ``event_hash``. Any mismatch is reported in
    ``broken``; rows older than the chain (NULL hashes) are skipped.
    """

    rows = (
        db.execute(
            select(AuditEventRow).order_by(AuditEventRow.created_at, AuditEventRow.id).limit(limit)
        )
        .scalars()
        .all()
    )
    return verify_chain(list(rows))
