"""Audit endpoint accepts ``from`` / ``to`` query params per PLAN §4."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agenticos_shared.models import AuditEventRow


def _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="admin@x", is_superuser=True)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="admin")
    login_as(u)
    return u, w


def _seed(db, w, *, count: int, base: datetime) -> list[AuditEventRow]:
    rows = []
    for i in range(count):
        r = AuditEventRow(
            id=uuid4(),
            tenant_id=w.tenant_id,
            workspace_id=w.id,
            action=f"sample.{i}",
            decision="allow",
            payload={},
            created_at=base + timedelta(minutes=i),
        )
        db.add(r)
        rows.append(r)
    db.commit()
    return rows


def test_from_to_filters_inclusive_window(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    base = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
    _seed(db, w, count=10, base=base)
    # Window covers minutes 3-6 inclusive.
    r = client.get(
        f"/api/v1/workspaces/{w.id}/audit",
        params={
            "from": (base + timedelta(minutes=3)).isoformat(),
            "to": (base + timedelta(minutes=6)).isoformat(),
        },
    )
    assert r.status_code == 200
    actions = {row["action"] for row in r.json()}
    assert actions == {"sample.3", "sample.4", "sample.5", "sample.6"}


def test_legacy_since_until_aliases_still_work(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    base = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
    _seed(db, w, count=4, base=base)
    r = client.get(
        f"/api/v1/workspaces/{w.id}/audit",
        params={"since": (base + timedelta(minutes=2)).isoformat()},
    )
    assert r.status_code == 200
    actions = {row["action"] for row in r.json()}
    assert "sample.0" not in actions
    assert "sample.3" in actions
