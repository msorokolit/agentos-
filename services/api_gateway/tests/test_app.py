from fastapi.testclient import TestClient

from api_gateway.main import app


def test_healthz() -> None:
    c = TestClient(app)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["service"] == "api-gateway"


def test_readyz() -> None:
    c = TestClient(app)
    r = c.get("/readyz")
    assert r.status_code == 200


def test_openapi() -> None:
    c = TestClient(app)
    r = c.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "api-gateway"
