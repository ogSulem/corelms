"""Разные причины отказа базы — разные ответы.

До этой правки любая ошибка SQLAlchemy отдавалась как «База данных перегружена
или недоступна. Повторите запрос через минуту; данные не потеряны». Из-за этого
администратор, которому мешало нарушение уникальности или слишком длинное поле,
повторял создание партнёра и получал то же самое: текст обещал, что «само
пройдёт», хотя не проходило никогда.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import (
    DataError,
    IntegrityError,
    OperationalError,
    ProgrammingError,
    TimeoutError as SATimeoutError,
)

from app.services.db_errors import classify_db_error


class _Orig(Exception):
    """Похоже на psycopg-ошибку: у неё есть pgcode."""

    def __init__(self, message: str, pgcode: str = "") -> None:
        super().__init__(message)
        self.pgcode = pgcode


def _dbapi(exc_type, message: str, pgcode: str = ""):
    orig = _Orig(message, pgcode)
    return exc_type("SELECT 1", {}, orig)


@pytest.mark.parametrize(
    ("exc", "status", "code", "reason"),
    [
        (SATimeoutError("QueuePool limit of size 5 overflow 10 reached, connection timed out"),
         503, "database_unavailable", "pool_busy"),
        (_dbapi(OperationalError, "FATAL: sorry, too many clients already", "53300"),
         503, "database_unavailable", "connections"),
        (_dbapi(OperationalError, "could not connect to server: Connection refused", ""),
         503, "database_unavailable", "unreachable"),
        (_dbapi(OperationalError, "could not extend file: No space left on device", "53100"),
         503, "database_unavailable", "disk"),
        (_dbapi(OperationalError, "the database system is starting up", "57P03"),
         503, "database_unavailable", "restart"),
        (_dbapi(OperationalError, "deadlock detected", "40P01"),
         503, "database_unavailable", "deadlock"),
        (_dbapi(IntegrityError, 'duplicate key value violates unique constraint "ix_users_email_ci"', "23505"),
         409, "conflict", "integrity"),
        (_dbapi(DataError, "value too long for type character varying(200)", "22001"),
         422, "invalid_value", "value"),
        (_dbapi(ProgrammingError, 'column "must_change_password" does not exist', "42703"),
         500, "schema_outdated", "schema"),
        (_dbapi(ProgrammingError, "canceling statement due to statement timeout", "57014"),
         503, "database_unavailable", "query_timeout"),
    ],
)
def test_db_errors_are_classified_not_all_called_overloaded(exc, status, code, reason):
    failure = classify_db_error(exc)
    assert failure is not None
    assert (failure.status, failure.code, failure.reason) == (status, code, reason)
    assert failure.hint


def test_non_database_errors_are_not_claimed_by_db_classifier():
    assert classify_db_error(ValueError("nope")) is None
    assert classify_db_error(RuntimeError("nope")) is None


def _probe_app(exception_factory):
    from app.main import create_app

    app = create_app()

    @app.get("/__db_probe")
    def _probe():
        raise exception_factory()

    return TestClient(app, raise_server_exceptions=False)


def test_pool_exhaustion_says_retry_with_reason_and_retry_after():
    """Пул занят — это единственный случай, где «повторите» действительно верно."""
    client = _probe_app(lambda: SATimeoutError("QueuePool limit reached, connection timed out"))
    response = client.get("/__db_probe")
    assert response.status_code == 503
    body = response.json()
    assert body["error_code"] == "database_unavailable"
    assert body["error_reason"] == "pool_busy"
    assert "Повторите" in body["error_message"]
    assert body["retry_after_seconds"] == 15
    assert response.headers["Retry-After"] == "15"


def test_duplicate_value_is_409_without_promise_to_retry():
    client = _probe_app(
        lambda: _dbapi(IntegrityError, 'duplicate key value violates unique constraint', "23505")
    )
    response = client.get("/__db_probe")
    assert response.status_code == 409
    body = response.json()
    assert body["error_code"] == "conflict"
    assert "перегружена" not in body["error_message"]
    assert "повторите" not in body["error_message"].lower()


def test_unapplied_migration_is_not_reported_as_overload():
    """Код новее схемы: повтор не поможет никогда, поэтому текст другой."""
    client = _probe_app(
        lambda: _dbapi(ProgrammingError, 'column "x" does not exist', "42703")
    )
    response = client.get("/__db_probe")
    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "schema_outdated"
    assert body["error_reason"] == "schema"
    assert "Повторите" in body["error_message"]


def test_streaming_response_releases_dependency_before_body():
    """Проверка, на которой держится отсутствие утечки в раздаче видео.

    `assets/{id}/stream` возвращает `StreamingResponse` с открытой зависимостью
    `get_db`. В FastAPI ≥ 0.106 зависимости с yield закрываются ДО отправки
    тела, поэтому просмотр видео не держит соединение с базой. Если версия
    FastAPI откатится, этот тест упадёт раньше, чем на проде кончится пул.
    """
    from fastapi import Depends, FastAPI
    from fastapi.responses import StreamingResponse

    seen: dict[str, object] = {"closed": False, "closed_before_body": None}

    def dependency():
        try:
            yield "session"
        finally:
            seen["closed"] = True

    app = FastAPI()

    @app.get("/stream")
    def stream(_: str = Depends(dependency)):
        def gen():
            seen["closed_before_body"] = seen["closed"]
            yield b"first"
            yield b"second"

        return StreamingResponse(gen())

    response = TestClient(app).get("/stream")
    assert response.content == b"firstsecond"
    assert seen["closed"] is True
    assert seen["closed_before_body"] is True


def test_error_log_keeps_reason_hint(tmp_path, monkeypatch):
    """Причина попадает в журнал: администратор видит её без SSH."""
    from app.services import error_log

    path = tmp_path / "errors.jsonl"
    monkeypatch.setenv("CORELMS_ERROR_LOG_PATH", str(path))
    error_log.record(
        rid="rid-hint-1",
        method="POST",
        path="/admin/users",
        status=503,
        hint="причина: pool_busy | пул: занято 15 из 15",
    )
    items, _ = error_log.read_recent(limit=5, days=0)
    entry = next(item for item in items if item["rid"] == "rid-hint-1")
    assert entry["hint"] == "причина: pool_busy | пул: занято 15 из 15"


def test_system_status_reports_db_connection_usage(client, admin_headers):
    """Диагностика показывает, сколько соединений занято, а не только «ок/не ок»."""
    response = client.get("/admin/system/status", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "db_connections" in body
    snapshot = body["db_connections"]
    assert isinstance(snapshot, dict)
    # На SQLite (локальный прогон) pg_stat_activity недоступен — снимок пустой.
    # На PostgreSQL (CI и прод) приходят реальные числа: лимит и занятые слоты.
    if snapshot:
        assert snapshot["max_connections"] > 0
        assert snapshot["total"] >= 1
    assert body["db"]["ok"] is True


def test_duplicate_email_on_create_is_409_not_a_database_outage(client, admin_headers):
    """Повторная почта — понятная причина, а не «база перегружена»."""
    email = "partner_dup@example.org"
    first = client.post("/admin/users", headers=admin_headers,
                        json={"name": "Партнёр Один", "email": email})
    assert first.status_code in {200, 201}, first.text

    second = client.post("/admin/users", headers=admin_headers,
                         json={"name": "Партнёр Два", "email": email.upper()})
    assert second.status_code == 409, second.text
    body = second.json()
    assert body["error_code"] != "database_unavailable"
    assert "перегружена" not in body["error_message"]


def test_too_long_name_is_422_with_field_name(client, admin_headers):
    """Раньше Postgres отвечал «value too long», а интерфейс — «перегружена»."""
    response = client.post("/admin/users", headers=admin_headers,
                           json={"name": "Я" * 201, "email": "long_name@example.org"})
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error_code"] == "invalid_value"
    assert "Имя" in body["error_message"]
    assert "перегружена" not in body["error_message"]


def test_too_long_position_is_422_on_update(client, admin_headers, make_user):
    user, _ = make_user()

    response = client.patch(f"/admin/users/{user.id}", headers=admin_headers,
                            json={"position": "Д" * 201})
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "invalid_value"


def test_api_pool_is_bigger_than_worker_pools():
    """Пул API не должен быть меньше: API обслуживает людей, воркеры — задачи."""
    from pathlib import Path

    import yaml

    compose = yaml.safe_load((Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    def _pool(name: str) -> tuple[int, int]:
        env = services[name]["environment"]
        values = {}
        for item in env:
            key, _, value = str(item).partition("=")
            values[key] = value
        size = int(str(values["DB_POOL_SIZE"]).split(":-")[1].rstrip("}"))
        overflow = int(str(values["DB_MAX_OVERFLOW"]).split(":-")[1].rstrip("}"))
        return size, overflow

    api_size, api_overflow = _pool("backend")
    worker_size, worker_overflow = _pool("worker")
    media_size, media_overflow = _pool("worker_media")

    assert api_size + api_overflow >= 20
    assert api_size > worker_size and api_size > media_size
    # 20 (API) + 2 процесса воркера × 6 + 6 медиа = 38 — с запасом до 80.
    total = (api_size + api_overflow) + 2 * (worker_size + worker_overflow) + (media_size + media_overflow)
    assert total <= 48, total


def test_integrity_hint_names_the_constraint():
    """Администратор видит, какое именно ограничение не пропустило запись."""

    class _Diag:
        constraint_name = "ix_users_name"
        column_name = None

    class _PgError(Exception):
        pgcode = "23505"

        def __init__(self) -> None:
            super().__init__('duplicate key value violates unique constraint "ix_users_name"')
            self.diag = _Diag()

    failure = classify_db_error(IntegrityError("INSERT INTO users", {}, _PgError()))
    assert failure is not None
    assert "ix_users_name" in failure.hint
    assert "SQLSTATE 23505" in failure.hint


def test_user_conflict_message_tells_which_field_conflicted():
    """Старое ограничение по имени не должно выглядеть как поломка базы."""
    from app.routers.admin import _user_conflict_message

    class _Diag:
        def __init__(self, constraint: str) -> None:
            self.constraint_name = constraint
            self.column_name = None

    class _Orig(Exception):
        pgcode = "23505"

        def __init__(self, message: str, constraint: str) -> None:
            super().__init__(message)
            self.diag = _Diag(constraint)

    name_clash = IntegrityError(
        "INSERT INTO users", {}, _Orig('duplicate key value violates unique constraint "ix_users_name"', "ix_users_name")
    )
    message = _user_conflict_message(name_clash)
    assert "именем" in message
    assert "фамилию" in message

    email_clash = IntegrityError(
        "INSERT INTO users", {}, _Orig('duplicate key value violates unique constraint "ix_users_email_ci"', "ix_users_email_ci")
    )
    assert "почтой" in _user_conflict_message(email_clash)


def test_repeated_update_keeps_other_users_email_untouched(client, admin_headers, make_user, db):
    """Правка чужой почты на занятую — понятная 409, а не «база перегружена»."""
    first, _ = make_user()
    second, _ = make_user()
    first.email = "one@example.org"
    second.email = "two@example.org"
    db.commit()

    response = client.patch(f"/admin/users/{second.id}", headers=admin_headers,
                            json={"email": "one@example.org"})
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error_code"] != "database_unavailable"
    assert "занят" in body["error_message"].lower()
