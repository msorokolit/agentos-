"""Model capability gating.

When an agent declares ``tool_ids`` we expect the configured ``model_alias``
to expose the ``tool_use`` capability; similarly an agent with a
``rag_collection_id`` (or ``config.rag_enabled=true``) should be backed
by a model whose ``capabilities.context_window`` is large enough to fit
retrieved chunks.

Models register capabilities under ``capabilities.{tool_use, vision,
json_mode, context_window}`` (free-form dict). We resolve a model alias
by hitting the llm-gateway's ``/admin/models`` endpoint (cached per
process for ``CACHE_TTL`` seconds) so this check is cheap.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from agenticos_shared.errors import NotFoundError, ValidationError
from agenticos_shared.logging import get_logger

from .settings import Settings

log = get_logger(__name__)


CACHE_TTL = 30.0
_cache: dict[str, dict[str, Any]] = {}
_cache_at: float = 0.0


async def _fetch_models(settings: Settings) -> dict[str, dict[str, Any]]:
    """Return ``{alias: model_row}`` from the llm-gateway, cached briefly."""

    global _cache, _cache_at
    now = time.monotonic()
    if _cache and (now - _cache_at) < CACHE_TTL:
        return _cache

    headers: dict[str, str] = {}
    if settings.llm_gateway_internal_token:
        headers["Authorization"] = f"Bearer {settings.llm_gateway_internal_token}"
    url = f"{settings.llm_gateway_url.rstrip('/')}/admin/models"
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=headers) as c:
            r = await c.get(url)
    except httpx.HTTPError as exc:
        log.warning("model_capability_fetch_failed", error=str(exc))
        return _cache  # best-effort: fall back to last-known cache

    if r.status_code >= 400:
        log.warning(
            "model_capability_fetch_status",
            status=r.status_code,
            body=r.text[:200],
        )
        return _cache
    rows = r.json() or []
    _cache = {row["alias"]: row for row in rows if isinstance(row, dict) and row.get("alias")}
    _cache_at = now
    return _cache


def _clear_cache() -> None:
    """Test helper to drop the registry cache between tests."""

    global _cache, _cache_at
    _cache = {}
    _cache_at = 0.0


async def ensure_model_supports(
    *,
    alias: str,
    needs_tool_use: bool,
    needs_rag: bool,
    settings: Settings,
) -> None:
    """Validate that ``alias`` exposes the capabilities the agent needs.

    Raises:
        NotFoundError: if the alias isn't registered.
        ValidationError: if a needed capability is missing.

    Falls back to a no-op when the registry is unreachable so we never
    block agent CRUD on a transient outage.
    """

    if not alias:
        return  # creation flow may default later

    models = await _fetch_models(settings)
    if not models:
        log.warning("model_capabilities_unknown_skip", alias=alias)
        return

    row = models.get(alias)
    if row is None:
        raise NotFoundError(f"model alias '{alias}' is not registered")

    if not row.get("enabled", True):
        raise ValidationError(f"model alias '{alias}' is disabled")

    kind = row.get("kind", "chat")
    if kind != "chat":
        raise ValidationError(f"model alias '{alias}' has kind={kind!r}, agents need a chat model")

    caps = (row.get("capabilities") or {}) if isinstance(row.get("capabilities"), dict) else {}
    if needs_tool_use and not bool(caps.get("tool_use")):
        raise ValidationError(
            f"model alias '{alias}' does not declare capabilities.tool_use=true; "
            "register it with that capability or pick a different model",
        )
    if needs_rag and caps.get("context_window") is not None:
        try:
            ctx = int(caps["context_window"])
        except Exception:
            ctx = 0
        if 0 < ctx < 4096:
            raise ValidationError(
                f"model alias '{alias}' context_window={ctx} is too small for RAG; "
                "need at least 4096 tokens",
            )
