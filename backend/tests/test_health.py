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


def test_health_version_reports_deployed_build(monkeypatch):
    """Версия кода видна снаружи: по ней проверяется, применился ли деплой."""
    monkeypatch.setenv("APP_VERSION", "ae7074d-2026-10-30_20-00")
    from app.routers import health as health_module

    app = create_app()
    client = TestClient(app)

    r = client.get("/health/version")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "ae7074d-2026-10-30_20-00"
    assert body["started_at"]
    assert health_module.version()["version"] == "ae7074d-2026-10-30_20-00"


def test_health_version_without_env_is_dev(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    from app.routers import health as health_module

    assert health_module.version()["version"] == "dev"
