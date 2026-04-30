"""Admin endpoints not tied to a specific resource (PLAN \u00a74)."""

from __future__ import annotations

import time
from typing import Annotated, Any

import httpx
from agenticos_shared.auth import Principal
from agenticos_shared.logging import get_logger
from fastapi import APIRouter, Depends

from ..auth.deps import require_admin
from ..settings import Settings, get_settings

router = APIRouter(prefix="/admin", tags=["admin"])
log = get_logger(__name__)


_SERVICES: tuple[tuple[str, str], ...] = (
    ("llm-gateway", "llm_gateway_url"),
    ("agent-runtime", "agent_runtime_url"),
    ("tool-registry", "tool_registry_url"),
    ("knowledge-svc", "knowledge_svc_url"),
)


async def _probe(name: str, url: str, *, timeout: float = 3.0) -> dict[str, Any]:
    if not url:
        return {"name": name, "ok": False, "error": "url_unset"}
    full = f"{url.rstrip('/')}/healthz"
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(full)
    except httpx.HTTPError as exc:
        return {
            "name": name,
            "ok": False,
            "url": full,
            "error": str(exc)[:200],
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
    return {
        "name": name,
        "ok": r.status_code < 400,
        "url": full,
        "status": r.status_code,
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }


@router.get("/health")
async def aggregate_health(
    _: Annotated[Principal, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Aggregate downstream health (PLAN §4 ``GET /admin/health``).

    Probes every internal service's ``/healthz`` and returns a flat
    summary plus an overall ``ok`` flag.
    """

    results: list[dict[str, Any]] = []
    for name, attr in _SERVICES:
        url = getattr(settings, attr, None)
        results.append(await _probe(name, url))
    overall = all(r["ok"] for r in results) if results else True
    return {"ok": overall, "services": results}
