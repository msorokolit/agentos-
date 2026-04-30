"""tool-registry settings."""

from __future__ import annotations

from functools import lru_cache

from agenticos_shared.settings import BaseServiceSettings
from pydantic import Field


class Settings(BaseServiceSettings):
    service_name: str = "tool-registry"
    knowledge_svc_url: str = Field(default="http://knowledge-svc:8084", alias="KNOWLEDGE_SVC_URL")
    egress_allow_hosts: list[str] = Field(default_factory=list, alias="EGRESS_ALLOW_HOSTS")
    max_response_bytes: int = Field(default=64 * 1024, alias="TOOL_MAX_RESPONSE_BYTES")
    invoke_timeout_seconds: float = Field(default=30.0, alias="TOOL_INVOKE_TIMEOUT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
