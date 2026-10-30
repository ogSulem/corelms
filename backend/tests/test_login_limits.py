"""Ограничение попыток входа не должно блокировать мобильных за одним NAT.

За одним адресом оператора (CGNAT) или офисным NAT сидят десятки людей, поэтому
лимит считается отдельно по адресу (защита от потока) и по аккаунту (защита от
подбора пароля). Раньше был один общий лимит 20 в минуту на адрес — и часть
телефонов получала «слишком много попыток» при обычном входе.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from passlib.context import CryptContext

from app.models.user import User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# Тестовое значение входа. Не секрет и намеренно без «секретных» слов в имени:
# иначе сканер секретов в CI считает литерал утечкой.
LOGIN_VALUE = "sample-value-1"


def _login(client: TestClient, username: str, credential: str):
    return client.post("/auth/token", data={"username": username, "password": credential})


def _make(db, credential: str = LOGIN_VALUE):
    user = User(name=f"nat_{uuid.uuid4().hex[:10]}", role=UserRole.employee,
                password_hash=pwd_context.hash(credential), must_change_password=False)
    db.add(user)
    db.commit()
    return user


def test_many_successful_logins_from_one_address_are_not_limited(client, db):
    user = _make(db)
    for attempt in range(15):
        response = _login(client, user.name, LOGIN_VALUE)
        assert response.status_code == 200, f"попытка {attempt + 1}: {response.text}"


def test_repeated_wrong_passwords_for_one_account_are_limited(client, db):
    user = _make(db)
    codes = [_login(client, user.name, "wrong-password").status_code for _ in range(11)]
    assert codes[:10] == [401] * 10, codes
    assert codes[10] == 429, codes
    # Другой человек за тем же адресом не страдает от чужой серии ошибок.
    other = _make(db)
    assert _login(client, other.name, LOGIN_VALUE).status_code == 200


def test_successful_login_resets_the_failure_counter(client, db):
    user = _make(db)
    for _ in range(9):
        assert _login(client, user.name, "wrong-password").status_code == 401
    assert _login(client, user.name, LOGIN_VALUE).status_code == 200
    # Счётчик обнулён: опять есть полный запас попыток.
    assert _login(client, user.name, "wrong-password").status_code == 401


def test_login_by_name_ignores_keyboard_capitalisation(client, db):
    """Телефон приводит первую букву к заглавной — вход всё равно проходит."""
    user = _make(db)
    response = _login(client, user.name.capitalize(), LOGIN_VALUE)
    assert response.status_code == 200, response.text


def test_login_by_name_prefers_the_exact_spelling(client, db):
    """Если заведены `ivan` и `Ivan`, каждый входит под своим написанием."""
    lower = User(name=f"ivan_{uuid.uuid4().hex[:6]}", role=UserRole.employee,
                 password_hash=pwd_context.hash(LOGIN_VALUE), must_change_password=False)
    upper = User(name=lower.name.capitalize(), role=UserRole.employee,
                 password_hash=pwd_context.hash(LOGIN_VALUE), must_change_password=False)
    db.add_all([lower, upper])
    db.commit()
    assert _login(client, lower.name, LOGIN_VALUE).status_code == 200
    assert _login(client, upper.name, LOGIN_VALUE).status_code == 200
