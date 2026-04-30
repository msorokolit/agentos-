"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from agenticos_shared.errors import AgenticOSError


class ProviderError(AgenticOSError):
    status = 502
    code = "provider_error"
    title = "LLM provider error"


class ProviderTimeoutError(ProviderError):
    status = 504
    code = "provider_timeout"
    title = "LLM provider timeout"


class LLMProvider(ABC):
    """Adapter for a concrete LLM endpoint.

    All implementations must accept and return the OpenAI-compatible
    request/response shapes as plain ``dict`` payloads. The router converts
    to/from pydantic models at the edges.
    """

    name: str = "abstract"
    endpoint: str
    model_name: str

    @abstractmethod
    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Non-streaming chat completion."""

    @abstractmethod
    def chat_stream(self, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Streaming chat completion. Yields OpenAI-shape chunk dicts."""

    @abstractmethod
    async def embed(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Embedding request."""

    @abstractmethod
    async def ping(self) -> int:
        """Reachability probe; returns latency in ms (raises on failure)."""
