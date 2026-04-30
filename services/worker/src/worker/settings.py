"""worker-specific settings."""

from __future__ import annotations

from functools import lru_cache

from agenticos_shared.settings import BaseServiceSettings
from pydantic import Field


class Settings(BaseServiceSettings):
    service_name: str = "worker"
    worker_concurrency: int = 4
    llm_gateway_url: str = Field(default="http://llm-gateway:8081", alias="LLM_GATEWAY_URL")
    memory_svc_url: str = Field(default="http://memory-svc:8085", alias="MEMORY_SVC_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
