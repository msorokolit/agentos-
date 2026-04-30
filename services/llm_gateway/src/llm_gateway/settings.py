"""llm-gateway-specific settings."""

from __future__ import annotations

from functools import lru_cache

from agenticos_shared.settings import BaseServiceSettings
from pydantic import Field


class Settings(BaseServiceSettings):
    service_name: str = "llm-gateway"

    # Per-workspace daily token budget. 0 disables the quota.
    daily_token_budget_per_workspace: int = Field(
        default=2_000_000, alias="DAILY_TOKEN_BUDGET_PER_WORKSPACE"
    )
    # Maximum requests/minute per workspace.
    rpm_per_workspace: int = Field(default=600, alias="RPM_PER_WORKSPACE")
    # Optional bearer to gate the gateway from outside (api-gateway sets it).
    internal_token: str | None = Field(default=None, alias="LLM_GATEWAY_INTERNAL_TOKEN")
    # When true, scrub outbound chat/embedding payloads of obvious PII
    # before forwarding to a provider.
    redact_outbound_payloads: bool = Field(default=False, alias="LLM_GATEWAY_REDACT_OUTBOUND")


@lru_cache
def get_settings() -> Settings:
    return Settings()
