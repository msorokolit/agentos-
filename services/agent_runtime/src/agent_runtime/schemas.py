"""Schemas for the agent-runtime."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AgentSpec(BaseModel):
    """Materialised agent definition passed into the runner."""

    id: UUID
    workspace_id: UUID
    name: str
    system_prompt: str = ""
    model_alias: str
    graph_kind: str = "react"
    config: dict[str, Any] = Field(default_factory=dict)
    tool_ids: list[str] = Field(default_factory=list)
    rag_collection_id: UUID | None = None


class RunRequest(BaseModel):
    """Synchronous, non-streaming run request (mostly for tests)."""

    agent: AgentSpec
    session_id: UUID
    user_id: UUID | None = None
    user_message: str
    history: list[dict[str, Any]] = Field(default_factory=list)


class StepEvent(BaseModel):
    """One step in the agent's execution. Streamed over NATS / WS."""

    type: str  # step|delta|tool_call|tool_result|final|error|citation
    session_id: UUID
    payload: dict[str, Any] = Field(default_factory=dict)


class RunResult(BaseModel):
    """Final result of a non-streaming run."""

    final_message: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    iterations: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None
