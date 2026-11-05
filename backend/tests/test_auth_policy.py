"""Политика входа настраивается из админки и действует во всех путях.

Раньше минимальная длина пароля и предел попыток входа жили только в `.env`:
изменить их из интерфейса было нельзя, а проверка дублировалась в четырёх
местах. Тесты фиксируют три вещи: значение из админки важнее окружения,
границы не дают ослабить вход, и все входные точки используют один помощник.
"""
from __future__ import annotations

import uuid

from passlib.context import CryptContext

from app.models.user import User, UserRole
from app.services.app_settings import (
    MAX_LOGIN_ATTEMPTS,
    MAX_PASSWORD_LENGTH,
    MIN_LOGIN_ATTEMPTS,
    MIN_PASSWORD_LENGTH,
)
from app.services.auth_policy import login_attempts_per_minute, password_min_length, password_problem

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

LONG_PASSWORD = "very-long-test-password"


def _save_platform(client, headers, **overrides):
    body = {"upload_max_bytes": 10 * 1024 * 1024, "allow_public_register": False,
            "password_min_length": 8, "login_attempts_per_minute": 10}
    body.update(overrides)
    return client.put("/admin/settings/platform", headers=headers, json=body)


def _make_login_user(db, *, credential: str = "test-value-1") -> User:
    user = User(name=f"policy_{uuid.uuid4().hex[:10]}", role=UserRole.employee,
                password_hash=pwd_context.hash(credential), must_change_password=False)
    db.add(user)
    db.commit()
    return user


def test_defaults_come_from_bounds_when_nothing_saved(client, admin_headers, db):
    response = client.get("/admin/settings/platform", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert MIN_PASSWORD_LENGTH <= payload["password_min_length"] <= MAX_PASSWORD_LENGTH
    assert MIN_LOGIN_ATTEMPTS <= payload["login_attempts_per_minute"] <= MAX_LOGIN_ATTEMPTS
    assert payload["limits"]["min_password_length"] == MIN_PASSWORD_LENGTH
    assert payload["limits"]["max_login_attempts"] == MAX_LOGIN_ATTEMPTS
    assert password_min_length(db) == payload["password_min_length"]
    assert login_attempts_per_minute(db) == payload["login_attempts_per_minute"]


def test_saved_policy_overrides_environment_and_is_auditable(client, admin_headers, db):
    response = _save_platform(client, admin_headers, password_min_length=12, login_attempts_per_minute=4)
    assert response.status_code == 200, response.text
    settings = response.json()["settings"]
    assert settings["password_min_length"] == 12
    assert settings["login_attempts_per_minute"] == 4
    assert settings["sources"]["password_min_length"] == "database"
    assert settings["sources"]["login_attempts_per_minute"] == "database"
    # Действует сразу, без перезапуска: помощник читает то же сохранённое значение.
    assert password_min_length(db) == 12
    assert login_attempts_per_minute(db) == 4


def test_policy_cannot_be_weakened_below_safe_bounds(client, admin_headers):
    assert _save_platform(client, admin_headers, password_min_length=MIN_PASSWORD_LENGTH - 1).status_code == 422
    assert _save_platform(client, admin_headers, password_min_length=MAX_PASSWORD_LENGTH + 1).status_code == 422
    assert _save_platform(client, admin_headers, login_attempts_per_minute=MIN_LOGIN_ATTEMPTS - 1).status_code == 422
    assert _save_platform(client, admin_headers, login_attempts_per_minute=MAX_LOGIN_ATTEMPTS + 1).status_code == 422


def test_reset_returns_policy_to_environment(client, admin_headers, db):
    assert _save_platform(client, admin_headers, password_min_length=14).status_code == 200
    assert client.delete("/admin/settings/platform", headers=admin_headers).status_code == 200
    response = client.get("/admin/settings/platform", headers=admin_headers)
    assert response.json()["sources"]["password_min_length"] == "environment"


def test_admin_policy_applies_to_public_registration(client, admin_headers, db):
    assert _save_platform(client, admin_headers, allow_public_register=True, password_min_length=12).status_code == 200
    short = client.post("/auth/register", json={"name": f"reg_{uuid.uuid4().hex[:8]}", "password": "12345678"})
    assert short.status_code == 400, short.text
    assert short.json()["error_message"] == "password too short"
    long = client.post("/auth/register", json={"name": f"reg_{uuid.uuid4().hex[:8]}", "password": "123456789012"})
    assert long.status_code in {200, 201}, long.text


def test_admin_policy_applies_to_change_password(client, make_user, admin_headers, db):
    # Токен привязан к хешу пароля, поэтому входим по-настоящему: иначе смена
    # хеша в базе отзывает выданный ранее токен.
    user, _ = make_user()
    user.password_hash = pwd_context.hash("current-password")
    db.add(user)
    db.commit()
    login = client.post("/auth/token", data={"username": user.name, "password": "current-password"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert _save_platform(client, admin_headers, password_min_length=12).status_code == 200
    short = client.post("/auth/change-password", headers=headers,
                        json={"current_password": "current-password", "new_password": "shortone"})
    assert short.status_code == 400, short.text
    ok = client.post("/auth/change-password", headers=headers,
                     json={"current_password": "current-password", "new_password": "longenough-12"})
    assert ok.status_code == 200, ok.text


def test_admin_created_and_reset_passwords_follow_policy(client, admin_headers, make_user, db):
    assert _save_platform(client, admin_headers, password_min_length=12).status_code == 200
    created = client.post("/admin/users", headers=admin_headers,
                          json={"name": f"emp_{uuid.uuid4().hex[:8]}", "email": f"emp_{uuid.uuid4().hex[:8]}@example.org",
                                "password": "short"})
    assert created.status_code == 422, created.text
    assert "не короче 12" in created.json()["error_message"]
    # Без пароля сервер генерирует свой — он всегда длиннее минимума.
    generated = client.post("/admin/users", headers=admin_headers,
                            json={"name": f"emp_{uuid.uuid4().hex[:8]}",
                                  "email": f"emp_{uuid.uuid4().hex[:8]}@example.org"})
    assert generated.status_code in {200, 201}, generated.text
    assert len(generated.json()["temp_password"]) >= 12

    target, _ = make_user()
    reset = client.post(f"/admin/users/{target.id}/reset-password", headers=admin_headers, json={"password": "short"})
    assert reset.status_code == 422, reset.text


def test_login_limit_from_admin_panel_stops_brute_force_earlier(client, admin_headers, db):
    user = _make_login_user(db)
    assert _save_platform(client, admin_headers, login_attempts_per_minute=3).status_code == 200
    codes = [client.post("/auth/token", data={"username": user.name, "password": "wrong-value"}).status_code
             for _ in range(4)]
    assert codes == [401, 401, 401, 429], codes


def test_successful_login_still_works_with_custom_limit(client, admin_headers, db):
    user = _make_login_user(db, credential=LONG_PASSWORD)
    assert _save_platform(client, admin_headers, login_attempts_per_minute=5).status_code == 200
    response = client.post("/auth/token", data={"username": user.name, "password": LONG_PASSWORD})
    assert response.status_code == 200, response.text


def test_password_problem_messages_are_human_readable(client, admin_headers, db):
    assert _save_platform(client, admin_headers, password_min_length=10).status_code == 200
    assert "не короче 10" in (password_problem("short", db=db) or "")
    assert password_problem("          ", db=db) is not None
    assert password_problem("0123456789", db=db) is None
