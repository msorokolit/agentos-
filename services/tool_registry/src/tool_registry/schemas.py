"""Schemas for the tool registry."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ToolKind = Literal["builtin", "http", "openapi", "mcp"]


class ToolDescriptor(BaseModel):
    """JSON-Schema-shaped tool description.

    Mirrors the OpenAI/Claude function-calling shape so it can be passed
    to LLM providers verbatim (after stripping connection details).
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


class ToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    display_name: str | None = None
    description: str | None = None
    kind: ToolKind
    descriptor: dict[str, Any] = Field(default_factory=dict)
    scopes: list[str] = Field(default_factory=list)
    workspace_id: UUID | None = None


class ToolUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    descriptor: dict[str, Any] | None = None
    scopes: list[str] | None = None
    enabled: bool | None = None


class ToolOut(BaseModel):
    id: UUID
    workspace_id: UUID | None
    name: str
    display_name: str | None
    description: str | None
    kind: ToolKind
    descriptor: dict[str, Any]
    scopes: list[str]
    enabled: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------
class ToolInvokeRequest(BaseModel):
    tool_id: UUID | None = None
    name: str | None = None
    workspace_id: UUID
    args: dict[str, Any] = Field(default_factory=dict)


class ToolInvokeResponse(BaseModel):
    ok: bool
    result: Any | None = None
    error: str | None = None
    truncated: bool = False
    latency_ms: int = 0
