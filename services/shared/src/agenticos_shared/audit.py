"""Audit event model + emitter.

Every mutating action and every LLM/tool call MUST emit an AuditEvent.
The emitter writes to both Postgres (durable) and NATS (fan-out for SIEM).
The DB write is best-effort within request scope; NATS is fire-and-forget.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .logging import get_logger

logger = get_logger(__name__)


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ERROR = "error"


class AuditEvent(BaseModel):
    """Append-only audit record."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID | None = None
    workspace_id: UUID | None = None
    actor_id: UUID | None = None
    actor_email: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    request_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    decision: Decision = Decision.ALLOW
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_json(self) -> str:
        return self.model_dump_json()


class AuditEmitter:
    """Emits audit events to NATS and (optionally) directly to the DB.

    The emitter is intentionally tiny — actual subscribers (audit-writer
    worker) are responsible for persistence. We log locally regardless.
    """

    def __init__(self, nats_publish: Any | None = None) -> None:
        # ``nats_publish`` is an async callable ``(subject, payload_bytes) -> None``.
        # Kept as ``Any`` to avoid hard-importing nats here.
        self._publish = nats_publish

    async def emit(self, event: AuditEvent, subject: str = "audit.events") -> None:
        logger.info(
            "audit",
            event_id=str(event.id),
            action=event.action,
            decision=event.decision.value,
            actor=event.actor_email,
            resource=f"{event.resource_type}:{event.resource_id}"
            if event.resource_type
            else None,
        )
        if self._publish is None:
            return
        try:
            await self._publish(subject, event.to_json().encode("utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("audit_publish_failed", error=str(exc))


def redact(value: Any, *, keep_chars: int = 0) -> str:
    """Redact a value for safe logging.

    >>> redact("hunter2")
    '***'
    >>> redact("hunter2", keep_chars=2)
    'hu***'
    """

    if value is None:
        return ""
    s = str(value)
    if keep_chars <= 0 or len(s) <= keep_chars:
        return "***"
    return f"{s[:keep_chars]}***"


def safe_payload(payload: dict[str, Any], *, drop_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return a payload with sensitive keys removed and string values truncated."""

    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k in drop_keys or any(s in k.lower() for s in ("secret", "password", "token", "api_key")):
            out[k] = "***"
            continue
        try:
            json.dumps(v)
            if isinstance(v, str) and len(v) > 4096:
                out[k] = v[:4096] + "...<truncated>"
            else:
                out[k] = v
        except (TypeError, ValueError):
            out[k] = repr(v)[:512]
    return out
