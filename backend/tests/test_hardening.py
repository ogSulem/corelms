"""Защитные пределы и запрет на повышение прав через публичные поля.

Три вещи, которые легко сломать незаметно:
- поле `role` в запросе регистрации не должно давать админа;
- роль меняет только superadmin, и никто не может понизить сам себя;
- платный вызов провайдера (кнопка «Проверить» в настройках ИИ) ограничен.
"""
from __future__ import annotations

import uuid

from app.models.user import User, UserRole


def _register(client, **extra):
    payload = {"name": f"reg_{uuid.uuid4().hex[:8]}", "password": "long-enough-password"}
    payload.update(extra)
    return client.post("/auth/register", json=payload)


def test_registration_ignores_requested_role(client, admin_headers):
    client.put("/admin/settings/platform", headers=admin_headers,
               json={"upload_max_bytes": 10 * 1024 * 1024, "allow_public_register": True})
    response = _register(client, role="superadmin")
    assert response.status_code in {200, 201}, response.text
    from app.db.session import SessionLocal

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"})
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "employee", me.json()


def test_admin_cannot_change_roles_but_superadmin_can(client, make_user, db):
    admin_token_headers = make_user(UserRole.admin)[1]
    target, _ = make_user(UserRole.employee)

    denied = client.patch(f"/admin/users/{target.id}", headers=admin_token_headers, json={"role": "admin"})
    assert denied.status_code == 403, denied.text
    assert db.get(User, target.id).role == UserRole.employee

    super_headers = make_user(UserRole.superadmin)[1]
    allowed = client.patch(f"/admin/users/{target.id}", headers=super_headers, json={"role": "partner"})
    assert allowed.status_code == 200, allowed.text
    db.expire_all()
    assert db.get(User, target.id).role == UserRole.partner


def test_superadmin_cannot_demote_self(client, make_user, db):
    owner, headers = make_user(UserRole.superadmin)
    response = client.patch(f"/admin/users/{owner.id}", headers=headers, json={"role": "employee"})
    assert response.status_code == 400, response.text
    db.expire_all()
    assert db.get(User, owner.id).role == UserRole.superadmin


def test_llm_probe_is_rate_limited(client, admin_headers, monkeypatch):
    from app.routers import admin as admin_router

    monkeypatch.setattr(admin_router, "generate_quiz_questions_ai", lambda **kwargs: [])
    payload = {"title": "Проба", "text": "Текст для проверки", "n_questions": 1}
    codes = [client.post("/admin/llm/probe", headers=admin_headers, json=payload).status_code
             for _ in range(11)]
    assert codes[:10] == [200] * 10, codes
    assert codes[10] == 429, codes
