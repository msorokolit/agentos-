"""GET /sessions/{id}/messages (top-level) + GET /admin/metrics."""

from __future__ import annotations

from uuid import uuid4

import respx


def _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="admin@x", is_superuser=True)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="admin")
    login_as(u)
    return u, w


# ---------------------------------------------------------------------------
# Top-level GET /sessions/{id}/messages
# ---------------------------------------------------------------------------
def test_top_level_session_messages_returns_history(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)

    aid = client.post(
        f"/api/v1/workspaces/{w.id}/agents",
        json={"name": "x", "slug": "alpha", "model_alias": "chat-default"},
    ).json()["id"]
    sid = client.post(
        f"/api/v1/workspaces/{w.id}/agents/{aid}/sessions",
        json={"title": "ad-hoc"},
    ).json()["id"]

    r = client.get(f"/api/v1/sessions/{sid}/messages")
    assert r.status_code == 200, r.text
    assert r.json() == []  # no messages yet, but reachable


def test_top_level_session_messages_404_unknown(client, make_tenant, make_user, login_as):
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    r = client.get(f"/api/v1/sessions/{uuid4()}/messages")
    assert r.status_code == 404


def test_top_level_session_messages_cross_tenant_404(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    """Bob's session UUID must 404 when fetched by an Alice token."""

    from agenticos_shared.models import Agent
    from agenticos_shared.models import Session as SessionRow

    # Tenant A + alice
    a_t = make_tenant(slug="acme")
    alice = make_user(a_t.id, email="alice@a")
    a_w = make_workspace(a_t.id, slug="alpha")
    add_member(a_w.id, alice.id, role="admin")

    # Tenant B + bob + a session there
    b_t = make_tenant(slug="globex")
    bob = make_user(b_t.id, email="bob@b")
    b_w = make_workspace(b_t.id, slug="bravo")
    add_member(b_w.id, bob.id, role="admin")

    agent = Agent(
        id=uuid4(),
        workspace_id=b_w.id,
        slug="x",
        name="X",
        model_alias="chat-default",
    )
    db.add(agent)
    db.flush()
    session = SessionRow(
        id=uuid4(), workspace_id=b_w.id, agent_id=agent.id, user_id=bob.id, meta={}
    )
    db.add(session)
    db.commit()

    login_as(alice)
    r = client.get(f"/api/v1/sessions/{session.id}/messages")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /admin/metrics aggregator
# ---------------------------------------------------------------------------
SAMPLE_METRICS = """\
# HELP http_requests_total Total HTTP requests.
# TYPE http_requests_total counter
http_requests_total{method="GET",path="/healthz",service="llm-gateway",status="200"} 12
http_requests_total{method="POST",path="/v1/chat/completions",service="llm-gateway",status="200"} 3
# HELP tokens_total Tokens used.
# TYPE tokens_total counter
tokens_total{direction="in",model="chat-default",workspace_id="ws-1"} 1500
tokens_total{direction="out",model="chat-default",workspace_id="ws-1"} 500
# HELP llm_cost_usd_total Estimated USD cost.
# TYPE llm_cost_usd_total counter
llm_cost_usd_total{model="chat-default",workspace_id="ws-1"} 0.0125
"""


def test_admin_metrics_aggregates_counters(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    with respx.mock(assert_all_called=False) as router:
        for host in (
            "http://llm-gateway:8081/metrics",
            "http://agent-runtime:8082/metrics",
            "http://tool-registry:8083/metrics",
            "http://knowledge-svc:8084/metrics",
        ):
            router.get(host).respond(200, text=SAMPLE_METRICS)
        r = client.get("/api/v1/admin/metrics")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # Each downstream contributed http_requests_total = 15 (12+3); total = 60.
    assert body["totals"]["http_requests_total"] == 60
    # tokens_total: 1500 + 500 = 2000 per service; 4 services = 8000.
    assert body["totals"]["tokens_total"] == 8000
    # cost: 0.0125 per service, 4 services.
    assert abs(body["totals"]["llm_cost_usd_total"] - 0.05) < 1e-9


def test_admin_metrics_marks_failing_service(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _login_admin(client, make_tenant, make_user, make_workspace, add_member, login_as)
    with respx.mock(assert_all_called=False) as router:
        router.get("http://llm-gateway:8081/metrics").respond(200, text=SAMPLE_METRICS)
        router.get("http://agent-runtime:8082/metrics").respond(503, text="bad")
        router.get("http://tool-registry:8083/metrics").respond(200, text=SAMPLE_METRICS)
        router.get("http://knowledge-svc:8084/metrics").respond(200, text=SAMPLE_METRICS)
        r = client.get("/api/v1/admin/metrics")
    body = r.json()
    assert body["ok"] is False
    bad = next(s for s in body["services"] if s["name"] == "agent-runtime")
    assert bad["ok"] is False


def test_admin_metrics_requires_admin(client, make_tenant, make_user, login_as):
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    r = client.get("/api/v1/admin/metrics")
    assert r.status_code == 403
