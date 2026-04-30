"""Security header middleware applies hardening headers on every response."""

from __future__ import annotations


def test_strict_csp_on_api_responses(client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "max-age=" in r.headers["strict-transport-security"]


def test_docs_csp_allows_inline_for_swagger(client) -> None:
    r = client.get("/docs")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "'unsafe-inline'" in csp
    assert "default-src 'self'" in csp
