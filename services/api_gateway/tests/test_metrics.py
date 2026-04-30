"""/metrics endpoint exposes Prometheus counters/histograms."""

from __future__ import annotations


def test_metrics_endpoint_returns_prometheus_text(client) -> None:
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    # Both our histogram + counter families should be advertised.
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body


def test_request_increments_http_counter(client, make_tenant, make_user, login_as) -> None:
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    # Trigger an authenticated request.
    assert client.get("/api/v1/me").status_code == 200

    body = client.get("/metrics").text
    # The path is normalised so the counter line is stable.
    assert (
        'http_requests_total{method="GET",path="/api/v1/me",service="api-gateway",status="200"}'
        in body
    )


def test_audit_emit_records_metric(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
) -> None:
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="admin")
    login_as(u)

    # POST a workspace member → triggers member.add audit emit.
    other = make_user(t.id, email="b@x")
    r = client.post(
        f"/api/v1/workspaces/{w.id}/members",
        json={"email": "b@x", "role": "member"},
    )
    assert r.status_code == 201
    _ = other

    body = client.get("/metrics").text
    assert 'audit_events_total{action="member.add",decision="allow"}' in body
