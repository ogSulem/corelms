"""Журнал запросов не должен пропадать из-за alembic, а health должен отвечать на HEAD."""

import logging
from logging.config import fileConfig
from pathlib import Path

from app.core.config import settings


def test_request_logging_survives_alembic_logging_reset(monkeypatch):
    """AUTO_MIGRATE_ON_START=true запускает alembic в том же процессе.

    alembic/env.py вызывает fileConfig, который ставит корневому логгеру
    уровень WARN. Раньше после этого basicConfig(level=INFO) был бесполезен:
    все строки о запросах молча терялись, и docker logs был пустым.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
        logging.getLogger("corelms").setLevel(logging.NOTSET)
        fileConfig(str(alembic_ini), disable_existing_loggers=False)
        assert root.level > logging.INFO, "alembic должен был уронить корневой уровень"
        assert logging.getLogger("corelms").isEnabledFor(logging.INFO) is False

        from app.main import create_app

        create_app()

        assert root.level <= logging.INFO
        assert logging.getLogger("corelms").isEnabledFor(logging.INFO) is True
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_health_endpoints_answer_head(client):
    """curl -I и мониторинг шлют HEAD: раньше они получали 405."""
    for path in ("/health", "/health/live"):
        response = client.head(path)
        assert response.status_code == 200, (path, response.status_code)


def test_ready_endpoint_answers_head(client, monkeypatch):
    monkeypatch.setattr(settings, "health_ready_check_s3", False, raising=False)
    response = client.head("/health/ready")
    assert response.status_code == 200


def test_server_error_is_logged_with_request_id(client, caplog):
    """Код из сообщения об ошибке должен находиться в журнале backend."""
    from app.main import create_app

    app = create_app()

    @app.get("/__logging_probe")
    def _probe():
        raise RuntimeError("проверка журнала")

    from fastapi.testclient import TestClient

    local = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="corelms"):
        response = local.get("/__logging_probe")

    assert response.status_code == 500
    rid = response.json()["request_id"]
    messages = [record.getMessage() for record in caplog.records]
    assert any(rid in message for message in messages), messages
    assert any("__logging_probe" in message and '"status": 500' in message for message in messages), messages
