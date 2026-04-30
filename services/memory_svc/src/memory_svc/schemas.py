"""Schemas for the memory service."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

MemoryScope = Literal["user", "agent", "session", "workspace"]


# ---------------------------------------------------------------------------
# Short-term (Redis) — the recent message buffer for a session.
# ---------------------------------------------------------------------------
class ShortTermAppend(BaseModel):
    workspace_id: UUID
    session_id: UUID
    role: str = Field(min_length=1, max_length=32)
    content: str
    max_messages: int = Field(default=40, ge=1, le=500)


class ShortTermItem(BaseModel):
    role: str
    content: str
    ts: float


class ShortTermResponse(BaseModel):
    session_id: UUID
    messages: list[ShortTermItem]


# ---------------------------------------------------------------------------
# Long-term (Postgres + pgvector) — durable summaries / facts.
# ---------------------------------------------------------------------------
class MemoryPut(BaseModel):
    workspace_id: UUID
    scope: MemoryScope
    owner_id: UUID | None = None
    key: str = Field(min_length=1, max_length=255)
    value: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    embed: bool = False
    embed_alias: str | None = None
    ttl_seconds: int | None = None


class MemoryItemOut(BaseModel):
    id: UUID
    workspace_id: UUID
    scope: MemoryScope
    owner_id: UUID | None
    key: str
    value: dict[str, Any]
    summary: str | None
    has_embedding: bool
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryQuery(BaseModel):
    workspace_id: UUID
    scope: MemoryScope | None = None
    owner_id: UUID | None = None
    key: str | None = None
    query: str | None = None
    embed_alias: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)
