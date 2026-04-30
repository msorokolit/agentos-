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
    Integer,
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
MODEL_PROVIDERS = ("ollama", "vllm", "openai_compat")
MODEL_KINDS = ("chat", "embedding")
DOCUMENT_STATUSES = ("pending", "parsing", "embedding", "ready", "failed")
TOOL_KINDS = ("builtin", "http", "openapi", "mcp")
MESSAGE_ROLES = ("system", "user", "assistant", "tool")
MEMORY_SCOPES = ("user", "agent", "session", "workspace")
API_KEY_SCOPES = ("read", "write", "admin")
POLICY_PACKAGES = ("tool_access", "data_access", "model_access")


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
# Models registry (Phase 2)
# ---------------------------------------------------------------------------
class ModelRow(Base):
    """LLM/embedding model registered for use by the llm-gateway."""

    __tablename__ = "model"

    id: Mapped[uuid.UUID] = _uuid_pk()
    alias: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(
        SAEnum(*MODEL_PROVIDERS, name="model_provider", native_enum=False),
        nullable=False,
    )
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(
        SAEnum(*MODEL_KINDS, name="model_kind", native_enum=False),
        nullable=False,
        default="chat",
    )
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    default_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Collection(Base):
    """Logical grouping of documents in a workspace."""

    __tablename__ = "collection"
    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_collection_ws_slug"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _uuid_fk("workspace.id")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Document(Base):
    """An uploaded document, optionally bound to a collection."""

    __tablename__ = "document"
    __table_args__ = (Index("ix_document_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _uuid_fk("workspace.id")
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(*DOCUMENT_STATUSES, name="document_status", native_enum=False),
        nullable=False,
        default="pending",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Chunk(Base):
    """A text chunk + embedding for a document.

    The ``embedding`` column is JSON in this cross-dialect declaration.
    The Phase 3 migration adds a ``vector(EMBED_DIM)`` column on
    PostgreSQL via raw SQL when the pgvector extension is available.
    """

    __tablename__ = "chunk"
    __table_args__ = (
        Index("ix_chunk_document_ord", "document_id", "ord"),
        Index("ix_chunk_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = _uuid_fk("workspace.id")
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Stored as JSON for portability; PG migration upgrades to vector(N).
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class TokenUsage(Base):
    """Per-call token usage. Aggregated by worker for dashboards."""

    __tablename__ = "token_usage"
    __table_args__ = (
        Index("ix_token_usage_workspace_created", "workspace_id", "created_at"),
        Index("ix_token_usage_alias_created", "model_alias", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    model_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )


# ---------------------------------------------------------------------------
# Tool registry (Phase 4)
# ---------------------------------------------------------------------------
class ToolBinding(Base):
    """Join table: agent ↔ tool (PLAN §3 ``tool_binding``).

    Provides referential integrity so deleting a tool also drops every
    agent's binding to it. The ``agent.tool_ids`` JSON list remains the
    fast lookup path for the runtime; this table mirrors it for
    join-friendly admin queries and ``ON DELETE CASCADE``.
    """

    __tablename__ = "tool_binding"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tool.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class ToolRow(Base):
    """Tool registered in a workspace (or globally if workspace_id is null).

    ``descriptor`` is a JSON-Schema-shaped object describing the tool's
    name, description, parameter schema, and per-kind connection details.
    """

    __tablename__ = "tool"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_tool_ws_name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(
        SAEnum(*TOOL_KINDS, name="tool_kind", native_enum=False),
        nullable=False,
    )
    descriptor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Agents + chat (Phase 5)
# ---------------------------------------------------------------------------
class Agent(Base):
    __tablename__ = "agent"
    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_agent_ws_slug"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _uuid_fk("workspace.id")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    graph_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="react")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    tool_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    rag_collection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Session(Base):
    __tablename__ = "session"
    __table_args__ = (Index("ix_session_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _uuid_fk("workspace.id")
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (Index("ix_message_session_created", "session_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        SAEnum(*MESSAGE_ROLES, name="message_role", native_enum=False),
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_call: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Agent versions — immutable snapshots per publish (PLAN §3)
# ---------------------------------------------------------------------------
class AgentVersion(Base):
    """Immutable snapshot of an agent at a published version."""

    __tablename__ = "agent_version"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_version"),
        Index("ix_agent_version_agent", "agent_id", "version"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# API keys — long-lived workspace bearer tokens (PLAN §3)
# ---------------------------------------------------------------------------
class ApiKey(Base):
    """A workspace-scoped API key.

    The plaintext token is **never** stored — only ``hashed_key`` (sha256 of
    the bearer the client uses). The ``prefix`` (first 8 chars of the
    plaintext) is kept to help admins identify keys.
    """

    __tablename__ = "api_key"
    __table_args__ = (
        UniqueConstraint("hashed_key", name="uq_api_key_hashed"),
        Index("ix_api_key_workspace", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _uuid_fk("workspace.id")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    hashed_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Policy bundles — uploaded Rego (PLAN §3, §4)
# ---------------------------------------------------------------------------
class PolicyBundle(Base):
    """A versioned Rego bundle.

    At most one bundle per ``(tenant_id, package, name)`` is ``active``;
    the policy_svc fetches the active row at load time.
    """

    __tablename__ = "policy_bundle"
    __table_args__ = (
        Index("ix_policy_active", "tenant_id", "package", "active"),
        Index("ix_policy_name_version", "tenant_id", "package", "name", "version"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    package: Mapped[str] = mapped_column(
        SAEnum(*POLICY_PACKAGES, name="policy_package", native_enum=False),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rego: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Memory (Phase 5/6)
# ---------------------------------------------------------------------------
class MemoryItem(Base):
    """Per-(workspace, scope, key) memory item.

    Scope values:
      * ``user``     — bound to a user_id
      * ``agent``    — bound to an agent_id
      * ``session``  — bound to a session_id
      * ``workspace``— shared across the workspace

    ``embedding`` is JSON cross-dialect; on PostgreSQL the migration
    upgrades it to ``vector(EMBED_DIM)`` (best-effort).
    """

    __tablename__ = "memory_item"
    __table_args__ = (
        Index("ix_memory_workspace_scope", "workspace_id", "scope"),
        Index("ix_memory_owner", "scope", "owner_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _uuid_fk("workspace.id")
    scope: Mapped[str] = mapped_column(
        SAEnum(*MEMORY_SCOPES, name="memory_scope", native_enum=False),
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


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
