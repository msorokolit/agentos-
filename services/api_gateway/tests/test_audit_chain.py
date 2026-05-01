"""Audit emitter chains rows + /admin/audit/verify endpoint."""

from __future__ import annotations

import asyncio

from agenticos_shared.audit import AuditEvent
from agenticos_shared.audit_chain import GENESIS_HASH, verify_chain
from agenticos_shared.models import AuditEventRow
from sqlalchemy import select


def _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="admin@x", is_superuser=True)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="admin")
    login_as(u)
    return t, u, w


def test_emitter_chains_rows_and_verify_endpoint(
    client, db_engine, db_sessionmaker, make_tenant, make_user, make_workspace, add_member, login_as
):
    """Emitting two events should chain them: row2.prev_hash == row1.event_hash."""

    t, u, _w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)

    from api_gateway.audit_bus import GatewayAuditEmitter, _NatsBus

    emitter = GatewayAuditEmitter(_NatsBus("nats://invalid"))
    asyncio.run(
        emitter.emit(
            AuditEvent(
                tenant_id=t.id,
                actor_id=u.id,
                actor_email=u.email,
                action="thing.create",
                resource_type="thing",
                resource_id="A",
            )
        )
    )
    asyncio.run(
        emitter.emit(
            AuditEvent(
                tenant_id=t.id,
                actor_id=u.id,
                actor_email=u.email,
                action="thing.update",
                resource_type="thing",
                resource_id="A",
            )
        )
    )

    with db_sessionmaker() as s:
        rows = (
            s.execute(select(AuditEventRow).order_by(AuditEventRow.created_at, AuditEventRow.id))
            .scalars()
            .all()
        )

    assert len(rows) >= 2
    chained = [r for r in rows if r.event_hash is not None]
    assert len(chained) >= 2
    # First chained row links back to GENESIS, the second links to the first.
    assert chained[0].prev_hash == GENESIS_HASH
    assert chained[1].prev_hash == chained[0].event_hash
    # Hashes are unique.
    assert chained[0].event_hash != chained[1].event_hash

    # Verify endpoint says clean.
    r = client.get("/api/v1/admin/audit/verify")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["broken_count"] == 0, body
    assert body["ok"] is True
    assert body["checked"] >= 2


def test_verify_detects_tampering(
    client, db_engine, db_sessionmaker, make_tenant, make_user, make_workspace, add_member, login_as
):
    """Mutating a row's payload after-the-fact must surface in /verify."""

    t, u, _w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)

    from api_gateway.audit_bus import GatewayAuditEmitter, _NatsBus

    emitter = GatewayAuditEmitter(_NatsBus("nats://invalid"))
    for i in range(3):
        asyncio.run(
            emitter.emit(
                AuditEvent(
                    tenant_id=t.id,
                    actor_id=u.id,
                    actor_email=u.email,
                    action=f"act-{i}",
                    payload={"i": i},
                )
            )
        )

    with db_sessionmaker() as s:
        rows = (
            s.execute(select(AuditEventRow).order_by(AuditEventRow.created_at, AuditEventRow.id))
            .scalars()
            .all()
        )
        # Tamper with the middle row's payload (no hash fix-up).
        target = [r for r in rows if r.event_hash is not None][1]
        target.payload = {"i": 999}
        s.merge(target)
        s.commit()
        # Re-read.
        rows = (
            s.execute(select(AuditEventRow).order_by(AuditEventRow.created_at, AuditEventRow.id))
            .scalars()
            .all()
        )

    out = verify_chain(list(rows))
    assert out["ok"] is False
    assert out["broken_count"] >= 1

    # And via the live endpoint.
    r = client.get("/api/v1/admin/audit/verify")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
