"""Request/response schemas for knowledge-svc."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
class CollectionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")
    description: str | None = None


class CollectionOut(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    slug: str
    description: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class DocumentOut(BaseModel):
    id: UUID
    workspace_id: UUID
    collection_id: UUID | None = None
    title: str
    mime: str | None = None
    sha256: str | None = None
    size_bytes: int = 0
    status: str
    error: str | None = None
    chunk_count: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class DocumentIngestRequest(BaseModel):
    """Internal payload — knowledge-svc accepts uploads as multipart;
    the api-gateway forwards as JSON when the body is small text content."""

    workspace_id: UUID
    collection_id: UUID | None = None
    title: str
    mime: str | None = None
    text: str
    embed_alias: str | None = None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
class SearchRequest(BaseModel):
    workspace_id: UUID
    query: str = Field(min_length=1)
    collection_id: UUID | None = None
    top_k: int = Field(default=8, ge=1, le=50)
    embed_alias: str | None = None


class SearchHit(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    ord: int
    text: str
    score: float
    meta: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
