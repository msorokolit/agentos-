"""OpenAI-compatible request/response schemas.

We replicate the subset our agents actually need. We deliberately don't
re-export ``openai`` types to keep this service self-contained.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ChatRole = Literal["system", "user", "assistant", "tool"]


# ---------------------------------------------------------------------------
# Chat completions
# ---------------------------------------------------------------------------
class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: dict[str, Any]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: ChatRole
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


class ToolDef(BaseModel):
    type: Literal["function"] = "function"
    function: dict[str, Any]


class ChatCompletionRequest(BaseModel):
    model: str = Field(..., description="Model alias registered in the gateway.")
    messages: list[ChatMessage]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | str | None = None
    stream: bool = False
    tools: list[ToolDef] | None = None
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    user: str | None = None
    # AgenticOS extensions (ignored by upstreams):
    workspace_id: UUID | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str | None = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: Usage = Field(default_factory=Usage)


# ---------------------------------------------------------------------------
# Streaming chunk format
# ---------------------------------------------------------------------------
class ChatDelta(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: ChatRole | None = None
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class ChatChunkChoice(BaseModel):
    index: int = 0
    delta: ChatDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatChunkChoice]


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
class EmbeddingRequest(BaseModel):
    model: str
    input: str | list[str]
    workspace_id: UUID | None = None


class Embedding(BaseModel):
    object: Literal["embedding"] = "embedding"
    embedding: list[float]
    index: int


class EmbeddingResponse(BaseModel):
    object: Literal["list"] = "list"
    data: list[Embedding]
    model: str
    usage: Usage = Field(default_factory=Usage)


# ---------------------------------------------------------------------------
# Models registry CRUD
# ---------------------------------------------------------------------------
class ModelCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=128)
    provider: Literal["ollama", "vllm", "openai_compat"]
    endpoint: str
    model_name: str
    kind: Literal["chat", "embedding"] = "chat"
    capabilities: dict[str, Any] = Field(default_factory=dict)
    default_params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ModelUpdate(BaseModel):
    endpoint: str | None = None
    model_name: str | None = None
    capabilities: dict[str, Any] | None = None
    default_params: dict[str, Any] | None = None
    enabled: bool | None = None


class ModelOut(BaseModel):
    id: UUID
    alias: str
    provider: str
    endpoint: str
    model_name: str
    kind: str
    capabilities: dict[str, Any]
    default_params: dict[str, Any]
    enabled: bool


class ModelTestResult(BaseModel):
    ok: bool
    latency_ms: int
    detail: str | None = None
