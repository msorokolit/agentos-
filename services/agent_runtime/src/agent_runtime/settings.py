"""agent-runtime settings."""

from __future__ import annotations

from functools import lru_cache

from agenticos_shared.settings import BaseServiceSettings
from pydantic import Field


class Settings(BaseServiceSettings):
    service_name: str = "agent-runtime"
    llm_gateway_url: str = Field(default="http://llm-gateway:8081", alias="LLM_GATEWAY_URL")
    tool_registry_url: str = Field(default="http://tool-registry:8083", alias="TOOL_REGISTRY_URL")
    knowledge_svc_url: str = Field(default="http://knowledge-svc:8084", alias="KNOWLEDGE_SVC_URL")
    memory_svc_url: str = Field(default="http://memory-svc:8085", alias="MEMORY_SVC_URL")
    max_iterations: int = Field(default=6, alias="AGENT_MAX_ITERATIONS")
    rag_default_top_k: int = Field(default=5, alias="AGENT_RAG_TOP_K")


@lru_cache
def get_settings() -> Settings:
    return Settings()
