"""Reusable health endpoints."""

from __future__ import annotations

from agenticos_shared.healthz import attach_health
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_health_endpoints() -> None:
    app = FastAPI()
    attach_health(app, service_name="x-svc", version="9.9.9")
    client = TestClient(app)

    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "x-svc"}

    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"

    r = client.get("/version")
    assert r.status_code == 200
    assert r.json() == {"service": "x-svc", "version": "9.9.9"}
