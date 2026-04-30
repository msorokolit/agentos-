"""knowledge-svc settings."""

from __future__ import annotations

from functools import lru_cache

from agenticos_shared.settings import BaseServiceSettings
from pydantic import Field


class Settings(BaseServiceSettings):
    service_name: str = "knowledge-svc"
    llm_gateway_url: str = Field(default="http://llm-gateway:8081", alias="LLM_GATEWAY_URL")
    chunk_size_tokens: int = Field(default=400, alias="CHUNK_SIZE_TOKENS")
    chunk_overlap_tokens: int = Field(default=60, alias="CHUNK_OVERLAP_TOKENS")
    max_chunks_per_doc: int = Field(default=5000, alias="MAX_CHUNKS_PER_DOC")
    # Use llm-gateway internal token for service-to-service.
    llm_gateway_internal_token: str | None = Field(default=None, alias="LLM_GATEWAY_INTERNAL_TOKEN")


@lru_cache
def get_settings() -> Settings:
    return Settings()
