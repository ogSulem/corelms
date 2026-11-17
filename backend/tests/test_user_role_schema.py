"""Роль обучающегося, которую принимает база.

Боевой отказ: `DataError: invalid input value for enum userrole: "employee"`
на `POST /admin/users`. В базе, созданной полгода назад, обучающиеся названы
`partner`, а значения `employee` в типе нет — значит форма «Добавить партнёра»
не могла сработать ни разу, и любой повтор давал тот же ответ.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import DataError

from app.models.user import UserRole
from app.services import user_roles
from app.services.db_errors import classify_db_error
from app.services.user_roles import pick_learner_role

LEGACY_LABELS = {"partner", "admin", "superadmin"}
FULL_LABELS = {"employee", "partner", "admin", "superadmin"}


@pytest.mark.parametrize(
    ("labels", "in_use", "expected"),
    [
        # Чистая база: каноническое имя роли.
        (FULL_LABELS, {}, UserRole.employee),
        # Старая база: значения employee нет — берём partner.
        (LEGACY_LABELS, {}, UserRole.partner),
        # После миграции 0030 значение employee появилось, но данные — partner:
        # продолжаем так, чтобы не заводить единственного «employee».
        (FULL_LABELS, {"partner": 88}, UserRole.partner),
        (FULL_LABELS, {"employee": 3, "partner": 5}, UserRole.partner),
        (FULL_LABELS, {"employee": 5, "partner": 1}, UserRole.employee),
        # Схему прочитать не удалось (SQLite в тестах) — ничего не меняем.
        (set(), {"partner": 10}, UserRole.employee),
        # В типе нет ни одной учебной роли: пусть ответит база своей ошибкой.
        ({"admin"}, {}, UserRole.employee),
    ],
)
def test_pick_learner_role_prefers_what_the_database_already_uses(labels, in_use, expected):
    assert pick_learner_role(labels, in_use) is expected


def test_schema_labels_are_read_where_the_type_exists(db):
    """SQLite — пусто (типа нет), PostgreSQL — реальные значения enum."""
    user_roles.clear_cache()
    labels = user_roles.schema_role_labels(db)
    user_roles.clear_cache()
    in_use = user_roles.used_learner_roles(db)
    if db.get_bind().dialect.name != "postgresql":
        assert labels == set()
        assert in_use == {}
    else:
        assert {"employee", "partner", "admin", "superadmin"} <= labels
        # Ключи — только учебные роли, значения — счётчики.
        assert set(in_use) <= {"employee", "partner"}


def test_learner_role_falls_back_to_partner(monkeypatch, db):
    monkeypatch.setattr(user_roles, "schema_role_labels", lambda _db: set(LEGACY_LABELS))
    monkeypatch.setattr(user_roles, "used_learner_roles", lambda _db: {"partner": 88})
    assert user_roles.learner_role(db) is UserRole.partner


def test_learner_role_keeps_using_partner_after_migration(monkeypatch, db):
    """Миграция добавила employee, но 88 человек уже partner — новых тоже partner."""
    monkeypatch.setattr(user_roles, "schema_role_labels", lambda _db: set(FULL_LABELS))
    monkeypatch.setattr(user_roles, "used_learner_roles", lambda _db: {"partner": 88})
    assert user_roles.learner_role(db) is UserRole.partner


def test_resolve_role_keeps_an_explicitly_requested_role(monkeypatch, db):
    """Суперадмин вправе явно назвать роль — база её принимает, значит не меняем."""
    monkeypatch.setattr(user_roles, "schema_role_labels", lambda _db: set(FULL_LABELS))
    monkeypatch.setattr(user_roles, "used_learner_roles", lambda _db: {"partner": 88})
    assert user_roles.resolve_role(db, UserRole.employee) is UserRole.employee
    assert user_roles.resolve_role(db, UserRole.partner) is UserRole.partner
    assert user_roles.resolve_role(db, UserRole.admin) is UserRole.admin


def test_resolve_role_replaces_a_role_absent_in_legacy_enum(monkeypatch, db):
    """На старой базе явный `employee` невозможен — подставляем учебную роль базы."""
    monkeypatch.setattr(user_roles, "schema_role_labels", lambda _db: set(LEGACY_LABELS))
    monkeypatch.setattr(user_roles, "used_learner_roles", lambda _db: {"partner": 88})
    assert user_roles.resolve_role(db, UserRole.employee) is UserRole.partner


def test_create_user_works_on_legacy_enum(client, admin_headers, monkeypatch):
    """Ключевой сценарий: добавить партнёра в базе, где роль называется partner."""
    from app.routers import admin as admin_router

    monkeypatch.setattr(admin_router, "learner_role", lambda _db: UserRole.partner)

    response = client.post(
        "/admin/users",
        headers=admin_headers,
        json={"name": "Новый партнёр", "email": "legacy_enum@example.org"},
    )
    assert response.status_code in {200, 201}, response.text
    assert response.json()["temp_password"]

    listed = client.get("/admin/users", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    row = next(u for u in listed.json()["items"] if u["email"] == "legacy_enum@example.org")
    assert row["role"] == "partner"


def test_enum_mismatch_is_reported_as_schema_problem():
    """Такой отказ — не «данные неверные» и не «повторите через минуту»."""

    class _Orig(Exception):
        pgcode = "22P02"

        def __init__(self) -> None:
            super().__init__('invalid input value for enum userrole: "employee"')

    failure = classify_db_error(DataError("INSERT INTO users", {}, _Orig()))
    assert failure is not None
    assert failure.code == "schema_outdated"
    assert failure.reason == "schema"
    assert "версии" in failure.message
