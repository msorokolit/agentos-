"""memory-svc settings."""

from __future__ import annotations

from functools import lru_cache

from agenticos_shared.settings import BaseServiceSettings
from pydantic import Field


class Settings(BaseServiceSettings):
    service_name: str = "memory-svc"
    llm_gateway_url: str = Field(default="http://llm-gateway:8081", alias="LLM_GATEWAY_URL")
    short_term_default_ttl: int = Field(default=3600, alias="SHORT_TERM_TTL_SECONDS")
    short_term_max_messages: int = Field(default=200, alias="SHORT_TERM_MAX_MESSAGES")


@lru_cache
def get_settings() -> Settings:
    return Settings()
