from fastapi.testclient import TestClient

from app.main import create_app


def test_health_ok():
    app = create_app()
    client = TestClient(app)

    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_health_live():
    app = create_app()
    client = TestClient(app)

    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json().get("status") == "live"
