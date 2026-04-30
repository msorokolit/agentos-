from fastapi.testclient import TestClient
from memory_svc.main import app


def test_healthz() -> None:
    c = TestClient(app)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["service"] == "memory-svc"


def test_openapi() -> None:
    c = TestClient(app)
    r = c.get("/openapi.json")
    assert r.status_code == 200
