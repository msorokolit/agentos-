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


# Counters we surface in the aggregated /admin/metrics view. Keep this
# list short: anything that's interesting at the operator level (RPS,
# error rate, token cost, audit, policy denies) should be here; deep
# per-service histograms stay accessible via Prometheus directly.
_INTERESTING_COUNTERS = (
    "http_requests_total",
    "tokens_total",
    "llm_cost_usd_total",
    "llm_request_timeouts_total",
    "tool_invocations_total",
    "policy_decisions_total",
    "audit_events_total",
    "audit_events_dropped_total",
)


def _parse_metric_text(text: str) -> dict[str, Any]:
    """Tiny Prometheus exposition parser.

    Extracts only the metric families in :data:`_INTERESTING_COUNTERS`
    and rolls them up into ``{family: total_sum_across_labels}``. We
    deliberately drop labels here — the caller wants a single number
    per family.
    """

    out: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        # ``family{label="..."} 12.5`` or ``family 12.5``
        name = line.split("{", 1)[0].split(" ", 1)[0]
        if name not in _INTERESTING_COUNTERS:
            continue
        try:
            value = float(line.rsplit(" ", 1)[1])
        except (ValueError, IndexError):
            continue
        out[name] = out.get(name, 0.0) + value
    return out


async def _scrape_metrics(name: str, url: str, *, timeout: float = 3.0) -> dict[str, Any]:
    if not url:
        return {"name": name, "ok": False, "error": "url_unset"}
    full = f"{url.rstrip('/')}/metrics"
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(full)
    except httpx.HTTPError as exc:
        return {"name": name, "ok": False, "error": str(exc)[:200]}
    if r.status_code >= 400:
        return {"name": name, "ok": False, "status": r.status_code}
    return {"name": name, "ok": True, "metrics": _parse_metric_text(r.text)}


@router.get("/metrics")
async def aggregate_metrics(
    _: Annotated[Principal, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Aggregate counters across downstream services (PLAN §4
    ``GET /admin/metrics`` proxied).

    Returns ``{ok, services: [{name, metrics: {family: total}}], totals}``
    where ``totals`` is the cross-service sum of every interesting
    counter. Use Prometheus directly for histograms / per-label slices;
    this endpoint is for at-a-glance ops UIs.
    """

    services: list[dict[str, Any]] = []
    totals: dict[str, float] = {fam: 0.0 for fam in _INTERESTING_COUNTERS}
    for name, attr in _SERVICES:
        url = getattr(settings, attr, None)
        s = await _scrape_metrics(name, url)
        services.append(s)
        if s.get("ok"):
            for fam, val in (s.get("metrics") or {}).items():
                totals[fam] = totals.get(fam, 0.0) + float(val)
    return {"ok": all(s.get("ok") for s in services), "services": services, "totals": totals}
