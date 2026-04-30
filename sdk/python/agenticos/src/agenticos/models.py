"""Pydantic-light response models for the AgenticOS SDK.

We deliberately use Pydantic v2 here so SDK consumers get type-checked
return values without us pulling in any extra dependency beyond what
``agenticos-shared`` already requires.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

WorkspaceRole = Literal["owner", "admin", "builder", "member", "viewer"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Workspace(_Base):
    id: UUID
    tenant_id: UUID
    name: str
    slug: str
    created_at: datetime


class Member(_Base):
    user_id: UUID
    email: str
    display_name: str | None = None
    role: WorkspaceRole
    added_at: datetime


class Tool(_Base):
    id: UUID
    workspace_id: UUID | None
    name: str
    display_name: str | None = None
    description: str | None = None
    kind: Literal["builtin", "http", "openapi", "mcp"]
    descriptor: dict[str, Any] = Field(default_factory=dict)
    scopes: list[str] = Field(default_factory=list)
    enabled: bool = True
    created_at: datetime


class Document(_Base):
    id: UUID
    workspace_id: UUID
    collection_id: UUID | None = None
    title: str
    mime: str | None = None
    sha256: str | None = None
    size_bytes: int = 0
    status: Literal["pending", "parsing", "embedding", "ready", "failed"]
    error: str | None = None
    chunk_count: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class SearchHit(_Base):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    ord: int
    text: str
    score: float
    meta: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(_Base):
    query: str
    hits: list[SearchHit]


class Agent(_Base):
    id: UUID
    workspace_id: UUID
    name: str
    slug: str
    description: str | None = None
    system_prompt: str = ""
    model_alias: str
    graph_kind: str = "react"
    config: dict[str, Any] = Field(default_factory=dict)
    tool_ids: list[str] = Field(default_factory=list)
    rag_collection_id: str | None = None
    version: int = 1
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Session(_Base):
    id: UUID
    agent_id: UUID
    workspace_id: UUID
    title: str | None = None
    created_at: datetime


class Message(_Base):
    id: UUID
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_call: dict[str, Any] | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    created_at: datetime


class ToolCall(_Base):
    id: str | None = None
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(_Base):
    id: str | None = None
    name: str
    ok: bool
    result: Any | None = None
    error: str | None = None


class RunResult(_Base):
    final_message: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    iterations: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None
    session_id: UUID | None = None
