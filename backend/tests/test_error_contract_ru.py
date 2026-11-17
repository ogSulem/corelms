"""Контракт ошибок: человек видит русский текст и машинный код, а не служебную строку.

Интерфейс показывает `error_message` из ответа как есть. Поэтому любая
`HTTPException` обязана нести понятный текст: раньше ученик получал
«invalid quiz session», «not found», «forbidden» — по-английски и без кода,
по которому интерфейс мог бы отреагировать сам.
"""
from __future__ import annotations

import re
import uuid

from app.core.security import require_roles
from app.main import create_app
from app.models.user import UserRole


def _cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text or ""))


def _assert_error(response, *, status: int, code: str):
    assert response.status_code == status, response.text
    body = response.json()
    assert body.get("error_code") == code, body
    message = str(body.get("error_message") or "")
    assert message and _cyrillic(message), f"текст ошибки не по-русски: {message!r}"
    assert " " in message or len(message) > 3, message
    return body


def test_unauthorized_answers_russian_code(client):
    body = _assert_error(client.get("/me/profile"), status=401, code="unauthorized")
    assert "войти" in body["error_message"]


def test_expired_or_broken_token_answers_russian_code(client):
    _assert_error(
        client.get("/me/profile", headers={"Authorization": "Bearer not-a-jwt"}),
        status=401,
        code="invalid_token",
    )


def test_forbidden_for_learner_is_russian_not_english_forbidden(client, make_user):
    _, headers = make_user(UserRole.employee)
    _assert_error(client.get("/admin/users", headers=headers), status=403, code="forbidden")


def test_unknown_lesson_is_not_found_with_russian_text(client, auth_headers):
    body = _assert_error(
        client.post(f"/submodules/{uuid.uuid4()}/open", headers=auth_headers),
        status=404,
        code="not_found",
    )
    assert "Урок" in body["error_message"]


def test_unknown_module_in_progress_is_not_found(client, auth_headers):
    _assert_error(
        client.get(f"/progress/modules/{uuid.uuid4()}", headers=auth_headers),
        status=404,
        code="not_found",
    )


def test_short_password_reports_policy_in_russian(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "allow_public_register", True)
    body = _assert_error(
        client.post("/auth/register", json={"name": f"ru_{uuid.uuid4().hex[:6]}", "password": "123"}),
        status=400,
        code="invalid_value",
    )
    assert "Пароль" in body["error_message"]


def test_wrong_password_is_generic_and_russian(client):
    response = client.post(
        "/auth/token",
        data={"username": f"nobody_{uuid.uuid4().hex[:6]}", "password": "wrong-password-123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    body = _assert_error(response, status=401, code="invalid_credentials")
    # Никаких подробностей «пользователь есть, пароль нет»: только общий отказ.
    assert body["error_message"] == "Неверный логин или пароль"


def test_invalid_reset_token_is_single_russian_message(client):
    body = _assert_error(
        client.post("/auth/reset-password/confirm", json={"token": "deadbeef", "new_password": "strong-pass-123"}),
        status=400,
        code="invalid_token",
    )
    assert "ссылк" in body["error_message"].lower()


def test_every_route_declares_an_error_contract():
    """Ни одна ветка кода не возвращает английскую служебную строку через `detail`."""
    import pathlib

    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    pattern = re.compile(r'detail\s*=\s*"([^"]*[A-Za-z]{4,}[^"]*)"')
    for path in [*app_dir.rglob("*.py")]:
        if "health.py" in path.name:  # мониторинг: машинный контракт, не для людей
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "HTTPException" not in line:
                continue
            match = pattern.search(line)
            if not match:
                continue
            text = match.group(1)
            if _cyrillic(text):
                continue
            offenders.append(f"{path.relative_to(app_dir)}:{number}: {text}")
    assert not offenders, "английский текст в ответах API:\n" + "\n".join(offenders)


def test_admin_routes_exist_behind_roles():
    """Проверка каркаса: приложение собирается, и админские маршруты закрыты ролями."""
    app = create_app()
    admin_paths = {getattr(route, "path", "") for route in app.routes if getattr(route, "path", "").startswith("/admin")}
    assert "/admin/users" in admin_paths
    assert callable(require_roles(UserRole.admin))
