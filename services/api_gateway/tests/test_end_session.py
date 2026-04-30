"""POST /workspaces/{id}/sessions/{id}/end marks ended_at + audits."""

from __future__ import annotations

from uuid import UUID

from agenticos_shared.models import Session as SessionRow


def _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")
    login_as(u)
    return u, w


def test_end_session_sets_ended_at_and_audits(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)

    r = client.post(
        f"/api/v1/workspaces/{w.id}/agents",
        json={"name": "x", "slug": "alpha", "model_alias": "chat-default"},
    )
    agent_id = r.json()["id"]

    s = client.post(f"/api/v1/workspaces/{w.id}/agents/{agent_id}/sessions", json={}).json()
    session_id = UUID(s["id"])

    r = client.post(f"/api/v1/workspaces/{w.id}/sessions/{session_id}/end")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == str(session_id)
    # Without redis the queue is unreachable; that's fine.
    assert body["queued"] is False
    assert body["job_id"] is None

    sess = db.get(SessionRow, session_id)
    assert sess.ended_at is not None

    from agenticos_shared.models import AuditEventRow

    rows = db.query(AuditEventRow).filter_by(action="session.end").all()
    assert len(rows) == 1
    assert rows[0].resource_id == str(session_id)


def test_end_session_unknown_404(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    from uuid import uuid4

    r = client.post(f"/api/v1/workspaces/{w.id}/sessions/{uuid4()}/end")
    assert r.status_code == 404
