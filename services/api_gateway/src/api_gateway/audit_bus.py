"""NATS-backed audit emitter for the api-gateway.

We attempt to connect to NATS at startup. If unavailable (dev mode without
NATS), audit events still get logged + written to the DB by the worker via
a fallback path: we also write a synchronous DB row best-effort.
"""

from __future__ import annotations

import asyncio
from typing import Any

import nats
from agenticos_shared.audit import AuditEmitter, AuditEvent
from agenticos_shared.db import session_scope
from agenticos_shared.logging import get_logger
from agenticos_shared.metrics import record_audit, record_audit_drop
from agenticos_shared.models import AuditEventRow

log = get_logger(__name__)


class _NatsBus:
    def __init__(self, url: str) -> None:
        self._url = url
        self._nc: Any | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._nc is not None:
            return
        try:
            self._nc = await nats.connect(
                self._url, allow_reconnect=True, max_reconnect_attempts=-1
            )
            log.info("nats.connected", url=self._url)
        except Exception as exc:  # pragma: no cover - dev path
            log.warning("nats.connect_failed", error=str(exc))

    async def publish(self, subject: str, payload: bytes) -> None:
        if self._nc is None:
            return
        try:
            await self._nc.publish(subject, payload)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("nats.publish_failed", error=str(exc), subject=subject)

    async def close(self) -> None:
        if self._nc is None:
            return
        try:
            await self._nc.drain()
        except Exception:  # pragma: no cover - defensive
            pass


class GatewayAuditEmitter(AuditEmitter):
    """Emitter that publishes to NATS *and* writes a row to Postgres.

    The DB write makes audit functional even before the worker is online;
    the worker can later be the canonical writer (Phase 6 — partitioning,
    retention).
    """

    def __init__(self, bus: _NatsBus) -> None:
        super().__init__(nats_publish=bus.publish)
        self._bus = bus

    async def emit(self, event: AuditEvent, subject: str = "audit.events") -> None:
        # Publish + log via parent first (always succeeds).
        await super().emit(event, subject=subject)
        try:
            record_audit(action=event.action, decision=event.decision.value)
        except Exception:
            pass
        # Best-effort DB write.
        try:
            with session_scope() as s:
                s.add(
                    AuditEventRow(
                        id=event.id,
                        tenant_id=event.tenant_id,
                        workspace_id=event.workspace_id,
                        actor_id=event.actor_id,
                        actor_email=event.actor_email,
                        action=event.action,
                        resource_type=event.resource_type,
                        resource_id=event.resource_id,
                        request_id=event.request_id,
                        ip=event.ip,
                        user_agent=event.user_agent,
                        decision=event.decision.value,
                        reason=event.reason,
                        payload=event.payload,
                        created_at=event.created_at,
                    )
                )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("audit_db_write_failed", error=str(exc))
            try:
                record_audit_drop(reason="db_write")
            except Exception:
                pass


_bus: _NatsBus | None = None
_emitter: GatewayAuditEmitter | None = None


async def init_audit(nats_url: str) -> None:
    global _bus, _emitter
    _bus = _NatsBus(nats_url)
    await _bus.connect()
    _emitter = GatewayAuditEmitter(_bus)


async def shutdown_audit() -> None:
    if _bus is not None:
        await _bus.close()


def get_emitter() -> GatewayAuditEmitter:
    if _emitter is None:
        # In tests we can construct a no-op emitter without NATS.
        bus = _NatsBus("nats://invalid")
        return GatewayAuditEmitter(bus)
    return _emitter
