"""Shared Prometheus metrics + ``/metrics`` mount.

All AgenticOS services share the same registry instance and the same set
of metric names so that the dashboards/alerts in
``deploy/compose/grafana/`` and ``deploy/compose/prometheus-alerts.yml``
work identically against any service.

Use ``record_*`` helpers from your code paths instead of touching the
metric objects directly — this keeps labels consistent and gives us a
single chokepoint to tweak cardinality later.
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI, Request
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Shared, process-wide registry. We deliberately do **not** use the module
# default to avoid colliding with whatever instrumentation libraries do.
REGISTRY = CollectorRegistry(auto_describe=True)

# ---------------------------------------------------------------------------
# HTTP server (one set per service, labelled by service)
# ---------------------------------------------------------------------------
http_requests_total = Counter(
    "http_requests_total",
    "HTTP requests received by the service.",
    ["service", "method", "path", "status"],
    registry=REGISTRY,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request handler duration.",
    ["service", "method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# LLM gateway
# ---------------------------------------------------------------------------
llm_request_latency_seconds = Histogram(
    "llm_request_latency_seconds",
    "Latency of an LLM provider call.",
    ["provider", "model", "alias", "kind"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
    registry=REGISTRY,
)
llm_request_timeouts_total = Counter(
    "llm_request_timeouts_total",
    "LLM provider timeouts.",
    ["provider", "alias"],
    registry=REGISTRY,
)
tokens_total = Counter(
    "tokens_total",
    "Tokens used (in/out) per workspace+model.",
    ["direction", "model", "workspace_id"],
    registry=REGISTRY,
)
llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Estimated USD cost of LLM calls (input + output, per registered rates).",
    ["model", "workspace_id"],
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------
tool_invocations_total = Counter(
    "tool_invocations_total",
    "Total tool invocations, labelled by ok=true/false.",
    ["tool", "kind", "ok"],
    registry=REGISTRY,
)
tool_invocation_latency_seconds = Histogram(
    "tool_invocation_latency_seconds",
    "Tool invocation duration.",
    ["tool", "kind"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30),
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Agent runtime
# ---------------------------------------------------------------------------
agent_step_latency_seconds = Histogram(
    "agent_step_latency_seconds",
    "Latency per ReAct graph node.",
    ["node"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60),
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Audit + policy
# ---------------------------------------------------------------------------
audit_events_total = Counter(
    "audit_events_total",
    "Audit events emitted.",
    ["action", "decision"],
    registry=REGISTRY,
)
audit_events_dropped_total = Counter(
    "audit_events_dropped_total",
    "Audit events dropped due to NATS/DB unavailability.",
    ["reason"],
    registry=REGISTRY,
)
policy_decisions_total = Counter(
    "policy_decisions_total",
    "Policy decisions evaluated.",
    ["package", "decision", "reason"],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Helpers — keep label cardinality bounded.
# ---------------------------------------------------------------------------
_PATH_REPLACE_PREFIXES: tuple[str, ...] = (
    "/api/v1/workspaces/",
    "/workspaces/",
    "/documents/",
    "/admin/models/",
    "/admin/api-keys/",
    "/items/",
    "/short-term/",
)


def _normalise_path(path: str) -> str:
    """Collapse UUIDs / numeric IDs in URLs so we don't blow up cardinality."""

    out_parts: list[str] = []
    for part in path.split("/"):
        if not part:
            out_parts.append(part)
            continue
        if len(part) >= 8 and any(c == "-" for c in part) and len(part) >= 32:
            out_parts.append(":id")
        elif part.isdigit():
            out_parts.append(":n")
        else:
            out_parts.append(part)
    return "/".join(out_parts) or "/"


def record_http(*, service: str, method: str, path: str, status: int, duration_s: float) -> None:
    norm = _normalise_path(path)
    http_requests_total.labels(service=service, method=method, path=norm, status=str(status)).inc()
    http_request_duration_seconds.labels(service=service, method=method, path=norm).observe(
        duration_s
    )


def record_tool_invocation(*, tool: str, kind: str, ok: bool, latency_ms: int) -> None:
    tool_invocations_total.labels(tool=tool, kind=kind, ok=str(ok).lower()).inc()
    tool_invocation_latency_seconds.labels(tool=tool, kind=kind).observe(latency_ms / 1000.0)


def record_llm_call(
    *,
    provider: str,
    alias: str,
    model: str,
    kind: str,
    latency_ms: int,
    prompt_tokens: int,
    completion_tokens: int,
    workspace_id: str | None,
    timeout: bool = False,
    cost_usd: float = 0.0,
) -> None:
    llm_request_latency_seconds.labels(
        provider=provider, model=model, alias=alias, kind=kind
    ).observe(latency_ms / 1000.0)
    if timeout:
        llm_request_timeouts_total.labels(provider=provider, alias=alias).inc()
    ws = workspace_id or "anon"
    if prompt_tokens:
        tokens_total.labels(direction="in", model=alias, workspace_id=ws).inc(prompt_tokens)
    if completion_tokens:
        tokens_total.labels(direction="out", model=alias, workspace_id=ws).inc(completion_tokens)
    if cost_usd > 0:
        llm_cost_usd_total.labels(model=alias, workspace_id=ws).inc(cost_usd)


def record_agent_step(*, node: str, latency_s: float) -> None:
    agent_step_latency_seconds.labels(node=node).observe(latency_s)


def record_audit(*, action: str, decision: str) -> None:
    audit_events_total.labels(action=action, decision=decision).inc()


def record_audit_drop(*, reason: str) -> None:
    audit_events_dropped_total.labels(reason=reason).inc()


def record_policy_decision(*, package: str, decision: str, reason: str | None = None) -> None:
    policy_decisions_total.labels(package=package, decision=decision, reason=reason or "n/a").inc()


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
class _MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, service_name: str, exclude_paths: Iterable[str] = ()) -> None:
        super().__init__(app)
        self._service = service_name
        self._exclude = tuple(exclude_paths)

    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(p) for p in self._exclude):
            return await call_next(request)
        import time as _t

        t0 = _t.monotonic()
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception:
            status = 500
            raise
        finally:
            try:
                record_http(
                    service=self._service,
                    method=request.method,
                    path=request.url.path,
                    status=status,
                    duration_s=_t.monotonic() - t0,
                )
            except Exception:
                pass


def attach_metrics(app: FastAPI, *, service_name: str) -> None:
    """Mount ``/metrics`` and the request middleware on a FastAPI app."""

    @app.get("/metrics", include_in_schema=False)
    async def _metrics() -> Response:
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    app.add_middleware(
        _MetricsMiddleware,
        service_name=service_name,
        exclude_paths=("/metrics", "/healthz", "/readyz"),
    )
