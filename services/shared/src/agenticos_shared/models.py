"""SQLAlchemy ORM models for AgenticOS.

This module mirrors the Alembic migrations under ``migrations/versions``.
Whenever you add/alter a model here, generate a migration with::

    make makemigration M="describe change"

Tables are intentionally minimal in Phase 0; later phases add more.

Types are kept cross-dialect (``Uuid``, ``Enum(native_enum=False)``,
``JSON``) so unit tests can run against SQLite while production runs on
Postgres + pgvector.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


# Use ``Uuid`` so SQLAlchemy picks PG UUID on PostgreSQL and CHAR(32) on
# SQLite/MySQL. ``as_uuid=True`` ensures we always get python uuid.UUID.
def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _uuid_fk(target: str, *, nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(target, ondelete="CASCADE"),
        nullable=nullable,
    )


WORKSPACE_ROLES = ("owner", "admin", "builder", "member", "viewer")
AUDIT_DECISIONS = ("allow", "deny", "error")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    workspaces: Mapped[list[Workspace]] = relationship(back_populates="tenant")


class Workspace(Base):
    __tablename__ = "workspace"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_workspace_tenant_slug"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _uuid_fk("tenant.id")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    tenant: Mapped[Tenant] = relationship(back_populates="workspaces")
    members: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "user_account"  # 'user' is reserved in postgres
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _uuid_fk("tenant.id")
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    oidc_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkspaceMember(Base):
    """Join table: user ↔ workspace, with a role."""

    __tablename__ = "workspace_member"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("user_account.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(
        SAEnum(*WORKSPACE_ROLES, name="workspace_role", native_enum=False),
        nullable=False,
        default="member",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    workspace: Mapped[Workspace] = relationship(back_populates="members")


# ---------------------------------------------------------------------------
# Audit (append-only)
# ---------------------------------------------------------------------------
class AuditEventRow(Base):
    """Persistent storage for AuditEvents. Append-only.

    Partitioning by month is configured later via raw SQL in a migration.
    """

    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_workspace_created", "workspace_id", "created_at"),
        Index("ix_audit_actor_created", "actor_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str] = mapped_column(
        SAEnum(*AUDIT_DECISIONS, name="audit_decision", native_enum=False),
        nullable=False,
        default="allow",
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
