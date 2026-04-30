"""Audit log explorer."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from agenticos_shared.models import AuditEventRow


def _setup_admin(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="admin@x", is_superuser=True)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="admin")
    login_as(u)
    return u, w


def test_audit_requires_admin(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="member")
    login_as(u)
    r = client.get(f"/api/v1/workspaces/{w.id}/audit")
    assert r.status_code == 403


def test_audit_filter_by_action(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _setup_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    # Plant some rows.
    for action in ["agent.run", "agent.run", "tool.invoke"]:
        db.add(
            AuditEventRow(
                id=uuid4(),
                tenant_id=w.tenant_id,
                workspace_id=w.id,
                action=action,
                decision="allow",
                payload={},
                created_at=datetime.now(tz=UTC),
            )
        )
    db.commit()

    r = client.get(f"/api/v1/workspaces/{w.id}/audit")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 3

    r2 = client.get(f"/api/v1/workspaces/{w.id}/audit?action=agent.run")
    assert r2.status_code == 200
    actions = {row["action"] for row in r2.json()}
    assert actions == {"agent.run"}


def test_audit_pagination(client, db, make_tenant, make_user, make_workspace, add_member, login_as):
    _, w = _setup_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    for _ in range(5):
        db.add(
            AuditEventRow(
                id=uuid4(),
                tenant_id=w.tenant_id,
                workspace_id=w.id,
                action="x",
                decision="allow",
                payload={},
                created_at=datetime.now(tz=UTC),
            )
        )
    db.commit()
    r = client.get(f"/api/v1/workspaces/{w.id}/audit?limit=2")
    assert r.status_code == 200
    assert len(r.json()) == 2
