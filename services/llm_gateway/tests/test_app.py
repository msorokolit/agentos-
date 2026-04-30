from fastapi.testclient import TestClient

from llm_gateway.main import app


def test_healthz() -> None:
    c = TestClient(app)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["service"] == "llm-gateway"


def test_openapi() -> None:
    c = TestClient(app)
    r = c.get("/openapi.json")
    assert r.status_code == 200
