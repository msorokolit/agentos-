"""Model registry — alias → provider+model lookup, in-memory cache.

Backed by the ``model`` Postgres table (Phase 2 migration). The cache is
re-populated on demand and on registry mutations.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from agenticos_shared.db import session_scope
from agenticos_shared.errors import NotFoundError
from agenticos_shared.models import ModelRow
from sqlalchemy import select


@dataclass(frozen=True)
class ResolvedModel:
    """Materialised model entry."""

    alias: str
    provider: str
    endpoint: str
    model_name: str
    kind: str
    capabilities: dict[str, Any]
    default_params: dict[str, Any]
    enabled: bool


_cache: dict[str, ResolvedModel] = {}
_cache_lock = asyncio.Lock()


async def reload_cache() -> None:
    """Re-fetch all models into memory."""

    async with _cache_lock:
        new_cache: dict[str, ResolvedModel] = {}
        with session_scope() as db:
            for row in db.execute(select(ModelRow)).scalars():
                new_cache[row.alias] = _row_to_resolved(row)
        _cache.clear()
        _cache.update(new_cache)


def _row_to_resolved(row: ModelRow) -> ResolvedModel:
    return ResolvedModel(
        alias=row.alias,
        provider=row.provider,
        endpoint=row.endpoint,
        model_name=row.model_name,
        kind=row.kind,
        capabilities=dict(row.capabilities or {}),
        default_params=dict(row.default_params or {}),
        enabled=row.enabled,
    )


async def resolve(alias: str) -> ResolvedModel:
    """Look up a registered alias."""

    if alias in _cache:
        m = _cache[alias]
    else:
        await reload_cache()
        if alias not in _cache:
            raise NotFoundError(f"model alias '{alias}' not registered")
        m = _cache[alias]

    if not m.enabled:
        from agenticos_shared.errors import ForbiddenError

        raise ForbiddenError(f"model '{alias}' is disabled")
    return m


def list_all() -> list[ResolvedModel]:
    return list(_cache.values())


# Test helper.
def _seed(models: list[ResolvedModel]) -> None:
    _cache.clear()
    for m in models:
        _cache[m.alias] = m
