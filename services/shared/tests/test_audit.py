"""Audit emitter, redaction, and safe payload helpers."""

from __future__ import annotations

from uuid import uuid4

import pytest

from agenticos_shared.audit import AuditEmitter, AuditEvent, Decision, redact, safe_payload


def test_redact_basic() -> None:
    assert redact(None) == ""
    assert redact("hunter2") == "***"
    assert redact("hunter2", keep_chars=2) == "hu***"
    assert redact("ab", keep_chars=4) == "***"


def test_safe_payload_drops_secrets() -> None:
    payload = {
        "username": "alice",
        "api_key": "sk-secret",
        "password": "p@ss",
        "token": "tok_123",
        "nested": {"ok": True},
    }
    safe = safe_payload(payload)
    assert safe["username"] == "alice"
    assert safe["api_key"] == "***"
    assert safe["password"] == "***"
    assert safe["token"] == "***"
    assert safe["nested"] == {"ok": True}


def test_safe_payload_truncates_long_strings() -> None:
    long = "x" * 5000
    safe = safe_payload({"big": long})
    assert safe["big"].endswith("<truncated>")
    assert len(safe["big"]) <= 4096 + len("...<truncated>")


def test_audit_event_roundtrip() -> None:
    e = AuditEvent(
        action="agent.run",
        actor_email="alice@example.com",
        decision=Decision.ALLOW,
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        payload={"foo": "bar"},
    )
    raw = e.to_json()
    again = AuditEvent.model_validate_json(raw)
    assert again.action == e.action
    assert again.decision == Decision.ALLOW


@pytest.mark.asyncio
async def test_emitter_without_publish_is_noop() -> None:
    em = AuditEmitter(nats_publish=None)
    await em.emit(AuditEvent(action="noop"))


@pytest.mark.asyncio
async def test_emitter_invokes_publish() -> None:
    received: list[tuple[str, bytes]] = []

    async def fake_publish(subject: str, payload: bytes) -> None:
        received.append((subject, payload))

    em = AuditEmitter(nats_publish=fake_publish)
    await em.emit(AuditEvent(action="agent.run"), subject="audit.events")
    assert len(received) == 1
    assert received[0][0] == "audit.events"
    assert b"agent.run" in received[0][1]
