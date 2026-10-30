"""Пул соединений и SSE-потоки: 500 из-за исчерпанного пула больше не «ошибка сервера»."""

import pytest
from sqlalchemy.exc import TimeoutError as SATimeoutError


def test_stream_dependency_releases_database_connection():
    """SSE-поток живёт минутами; соединение с БД не должно быть занято всё это время."""
    from app.db.session import SessionLocal, engine
    from app.core.security import get_current_user_stream  # noqa: F401  (импорт проверяет наличие)

    pool = engine.pool
    if not hasattr(pool, "checkedout"):
        pytest.skip("SQLite в тестах использует StaticPool — там нечего освобождать")
    before = pool.checkedout()

    db = SessionLocal()
    db.execute(__import__("sqlalchemy").text("select 1"))
    assert pool.checkedout() == before + 1

    # Так поступает потоковая зависимость: закрывает сессию до начала стрима.
    db.close()
    assert pool.checkedout() == before


def test_events_routes_use_stream_dependencies():
    """Ни один SSE-маршрут не должен зависеть от обычного get_current_user."""
    from fastapi.routing import APIRoute

    from app.main import create_app

    app = create_app()
    stream_paths = {"/modules/events", "/admin/jobs/events"}
    seen = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path not in stream_paths:
            continue
        seen.add(route.path)
        def _names(dep) -> set[str]:
            call = getattr(dep, "call", None)
            name = getattr(call, "__name__", "")
            return {name} if name else set()

        dependency_names = set()
        nested = set()
        for dep in route.dependant.dependencies:
            dependency_names |= _names(dep)
            for sub in getattr(dep, "dependencies", []):
                nested |= _names(sub)
        assert "get_current_user_stream" in dependency_names | nested, (route.path, dependency_names | nested)
    assert seen == stream_paths


def test_database_timeout_becomes_503_with_clear_message(client):
    """Исчерпанный пул — это 503 «повторите позже», а не 500 «ошибка сервера»."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()

    @app.get("/__db_pool_probe")
    def _probe():
        raise SATimeoutError("QueuePool limit of size 5 overflow 10 reached, connection timed out")

    local = TestClient(app, raise_server_exceptions=False)
    response = local.get("/__db_pool_probe")

    assert response.status_code == 503
    body = response.json()
    assert body["error_code"] == "database_unavailable"
    assert "Повторите" in body["error_message"]
    assert body["request_id"]


def test_pool_snapshot_is_available_for_diagnostics(client, admin_headers):
    response = client.get("/admin/system/status", headers=admin_headers)
    assert response.status_code == 200, response.text
    pool = response.json().get("db_pool")
    assert pool and "checked_out" in pool and "max_overflow" in pool
