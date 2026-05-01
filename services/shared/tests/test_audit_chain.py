"""Audit hash-chain helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from agenticos_shared.audit_chain import (
    GENESIS_HASH,
    compute_event_hash,
    verify_chain,
)


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _row(action: str, **extras):
    base = {
        "id": uuid4(),
        "tenant_id": None,
        "workspace_id": None,
        "actor_id": None,
        "actor_email": None,
        "action": action,
        "resource_type": None,
        "resource_id": None,
        "request_id": None,
        "ip": None,
        "user_agent": None,
        "decision": "allow",
        "reason": None,
        "payload": {},
        "created_at": datetime.now(tz=UTC),
        "prev_hash": None,
        "event_hash": None,
    }
    base.update(extras)
    return _Row(**base)


def test_compute_event_hash_is_deterministic():
    r = _row("a")
    h1 = compute_event_hash(r, prev_hash=GENESIS_HASH)
    h2 = compute_event_hash(r, prev_hash=GENESIS_HASH)
    assert h1 == h2
    assert len(h1) == 64


def test_compute_event_hash_changes_with_prev():
    r = _row("a")
    a = compute_event_hash(r, prev_hash=GENESIS_HASH)
    b = compute_event_hash(r, prev_hash="ff" * 32)
    assert a != b


def test_verify_chain_clean_run():
    rows = []
    prev = GENESIS_HASH
    for i in range(5):
        r = _row(f"act-{i}")
        r.prev_hash = prev
        r.event_hash = compute_event_hash(r, prev_hash=prev)
        prev = r.event_hash
        rows.append(r)

    out = verify_chain(rows)
    assert out["ok"] is True
    assert out["checked"] == 5
    assert out["broken_count"] == 0


def test_verify_chain_detects_tamper():
    rows = []
    prev = GENESIS_HASH
    for i in range(3):
        r = _row(f"act-{i}", payload={"i": i})
        r.prev_hash = prev
        r.event_hash = compute_event_hash(r, prev_hash=prev)
        prev = r.event_hash
        rows.append(r)

    # Tamper with row 1's payload — its hash and rows[2]'s prev_hash will
    # both fail to verify.
    rows[1].payload = {"i": 999}

    out = verify_chain(rows)
    assert out["ok"] is False
    assert out["broken_count"] >= 1
    bad_ids = {b["id"] for b in out["broken"]}
    assert str(rows[1].id) in bad_ids


def test_verify_chain_skips_unchained_rows():
    """Pre-chain rows (NULL event_hash) must not break verification."""

    legacy = _row("legacy")  # no hash fields set
    chained = []
    prev = GENESIS_HASH
    for i in range(2):
        r = _row(f"act-{i}")
        r.prev_hash = prev
        r.event_hash = compute_event_hash(r, prev_hash=prev)
        prev = r.event_hash
        chained.append(r)

    out = verify_chain([legacy, *chained])
    assert out["ok"] is True
    assert out["checked"] == 2
