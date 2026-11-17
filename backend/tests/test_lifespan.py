"""Старт/остановка приложения через lifespan, а не устаревший on_event."""
from __future__ import annotations


def test_lifespan_runs_startup_and_shutdown_and_serves_requests():
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "live"}
    # FastAPI больше не ругается на on_event: обработчиков событий нет.
    assert not getattr(app.router, "on_startup", []), "остался обработчик on_event(startup)"
    assert not getattr(app.router, "on_shutdown", []), "остался обработчик on_event(shutdown)"
    assert app.router.lifespan_context is not None
