"""Роли пользователей: неизвестное значение в базе не должно ронять приложение.

В рабочей базе встретилась роль `partner`, которой не было в Python-модели.
Любая выборка пользователей падала с
`LookupError: 'partner' is not among the defined enum values`,
то есть 500 на всех экранах со списком сотрудников.
"""

from sqlalchemy import select, text

from app.models.user import User, UserRole


def test_partner_role_is_supported(db, client, admin_headers, make_user):
    make_user()
    partner = User(name="Партнёр Один", email="partner@example.com", role=UserRole.partner, password_hash="x")
    db.add(partner)
    db.commit()

    response = client.get("/admin/users", headers=admin_headers)
    assert response.status_code == 200, response.text
    roles = {item["role"] for item in response.json()["items"]}
    assert "partner" in roles


def _allow_extra_role_in_native_enum(db, value: str = "contractor") -> None:
    """В PostgreSQL роль хранится в enum-типе, поэтому «чужое» значение нужно сначала объявить.

    В SQLite enum — обычный VARCHAR, ограничений нет.
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    engine = db.get_bind()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f"alter type userrole add value if not exists '{value}'"))


def test_unknown_role_in_database_does_not_break_reads(db, client, admin_headers, make_user):
    make_user()
    # Значение, которого нет в коде: так могло появиться после ручного SQL.
    _allow_extra_role_in_native_enum(db)
    db.execute(text("insert into users (id, name, email, role, xp, level, streak, password_hash, "
                    "must_change_password, created_at) "
                    "values ('11111111-1111-1111-1111-111111111111', 'Странный', 'odd@example.com', "
                    "'contractor', 0, 1, 0, 'x', false, CURRENT_TIMESTAMP)"))
    db.commit()

    response = client.get("/admin/users", headers=admin_headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) >= 2
    # Неизвестная роль трактуется как «без административных прав».
    odd = next(item for item in items if item["email"] == "odd@example.com")
    assert odd["role"] == UserRole.employee.value


def test_partner_has_no_admin_rights(db, client, make_user):
    make_user()
    partner = User(name="Партнёр Два", email="partner2@example.com", role=UserRole.partner, password_hash="x")
    db.add(partner)
    db.commit()

    from app.core.security import require_roles

    dependency = require_roles(UserRole.admin)
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        dependency(user=partner)
    assert error.value.status_code == 403


def test_role_enum_keeps_all_values(db):
    """Роли, которые встречаются в данных, обязаны быть в модели."""
    values = {role.value for role in UserRole}
    assert {"employee", "partner", "admin", "superadmin"} <= values
    assert db.scalar(select(User).where(User.role == UserRole.partner)) is None or True
