"""Policy bundle management — upload + activate Rego per package.

Tenant-level: bundles are scoped to ``principal.tenant_id``. Only
admin/owner/superuser can mutate. Every mutation is audited.

Activation is exclusive within a (tenant, package): activating a new
bundle deactivates whatever was previously active for the same package.
The OPA sidecar reloads its data via its own ``--watch`` config
(operational concern); this service is the source of truth.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from agenticos_shared.audit import AuditEvent
from agenticos_shared.auth import Principal
from agenticos_shared.errors import NotFoundError, ValidationError
from agenticos_shared.models import POLICY_PACKAGES, PolicyBundle
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..audit_bus import get_emitter
from ..auth.deps import require_admin
from ..db import get_db

router = APIRouter(prefix="/admin/policies", tags=["admin", "policies"])


class PolicyBundleCreate(BaseModel):
    package: str = Field(pattern=r"^(tool_access|data_access|model_access)$")
    name: str = Field(min_length=1, max_length=128)
    rego: str = Field(min_length=1)
    description: str | None = None
    activate: bool = False


class PolicyBundleOut(BaseModel):
    id: UUID
    tenant_id: UUID | None
    package: str
    name: str
    version: int
    sha256: str
    description: str | None
    active: bool
    created_at: datetime
    activated_at: datetime | None


class PolicyBundleDetail(PolicyBundleOut):
    rego: str


def _to_out(row: PolicyBundle) -> PolicyBundleOut:
    return PolicyBundleOut(
        id=row.id,
        tenant_id=row.tenant_id,
        package=row.package,
        name=row.name,
        version=row.version,
        sha256=row.sha256,
        description=row.description,
        active=row.active,
        created_at=row.created_at,
        activated_at=row.activated_at,
    )


@router.get("", response_model=list[PolicyBundleOut])
def list_bundles(
    principal: Annotated[Principal, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    package: str | None = None,
    active_only: bool = False,
) -> list[PolicyBundleOut]:
    q = select(PolicyBundle).where(PolicyBundle.tenant_id == principal.tenant_id)
    if package:
        if package not in POLICY_PACKAGES:
            raise ValidationError(f"unknown package '{package}'")
        q = q.where(PolicyBundle.package == package)
    if active_only:
        q = q.where(PolicyBundle.active.is_(True))
    q = q.order_by(PolicyBundle.created_at.desc())
    return [_to_out(r) for r in db.execute(q).scalars().all()]


@router.get("/{bundle_id}", response_model=PolicyBundleDetail)
def get_bundle(
    bundle_id: UUID,
    principal: Annotated[Principal, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> PolicyBundleDetail:
    row = db.get(PolicyBundle, bundle_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise NotFoundError("policy bundle not found")
    return PolicyBundleDetail(**_to_out(row).model_dump(), rego=row.rego)


@router.post("", response_model=PolicyBundleDetail, status_code=status.HTTP_201_CREATED)
async def upload_bundle(
    body: PolicyBundleCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> PolicyBundleDetail:
    # Tiny syntactic check: Rego files must declare a package directive.
    if not any(line.strip().startswith("package ") for line in body.rego.splitlines()):
        raise ValidationError("rego must include a 'package ...' directive")

    digest = hashlib.sha256(body.rego.encode("utf-8")).hexdigest()
    # Auto-version bump within (tenant, package, name).
    next_version = (
        db.execute(
            select(PolicyBundle.version)
            .where(
                PolicyBundle.tenant_id == principal.tenant_id,
                PolicyBundle.package == body.package,
                PolicyBundle.name == body.name,
            )
            .order_by(PolicyBundle.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        or 0
    ) + 1

    row = PolicyBundle(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        package=body.package,
        name=body.name,
        version=next_version,
        rego=body.rego,
        sha256=digest,
        description=body.description,
        active=False,
        created_by=principal.user_id,
    )
    db.add(row)
    db.flush()

    activated = False
    if body.activate:
        _activate(db, row=row)
        activated = True

    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="policy.upload",
            resource_type="policy_bundle",
            resource_id=str(row.id),
            payload={
                "package": body.package,
                "name": body.name,
                "version": next_version,
                "sha256": digest,
                "activated": activated,
            },
            ip=request.client.host if request.client else None,
        )
    )
    return PolicyBundleDetail(**_to_out(row).model_dump(), rego=row.rego)


@router.post("/{bundle_id}/activate", response_model=PolicyBundleOut)
async def activate_bundle(
    bundle_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> PolicyBundleOut:
    row = db.get(PolicyBundle, bundle_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise NotFoundError("policy bundle not found")
    _activate(db, row=row)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="policy.activate",
            resource_type="policy_bundle",
            resource_id=str(row.id),
            payload={"package": row.package, "name": row.name, "version": row.version},
            ip=request.client.host if request.client else None,
        )
    )
    return _to_out(row)


@router.delete("/{bundle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bundle(
    bundle_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    row = db.get(PolicyBundle, bundle_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise NotFoundError("policy bundle not found")
    if row.active:
        raise ValidationError("cannot delete an active bundle; activate another first")
    db.delete(row)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="policy.delete",
            resource_type="policy_bundle",
            resource_id=str(bundle_id),
            payload={"package": row.package, "name": row.name, "version": row.version},
            ip=request.client.host if request.client else None,
        )
    )


def _activate(db: Session, *, row: PolicyBundle) -> None:
    """Mark ``row`` active and deactivate any other bundle for the same package."""

    db.execute(
        update(PolicyBundle)
        .where(
            PolicyBundle.tenant_id == row.tenant_id,
            PolicyBundle.package == row.package,
            PolicyBundle.id != row.id,
            PolicyBundle.active.is_(True),
        )
        .values(active=False, activated_at=None)
    )
    row.active = True
    row.activated_at = datetime.now(tz=UTC)
