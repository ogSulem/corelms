"""Ссылка «задать пароль» из админки: выпуск, одноразовость, срок, уборка.

До этой правки экран `/reset-password` и ручка `POST /auth/reset-password/confirm`
существовали, но токен никто не выпускал: подсказка «перейдите по ссылке от
администратора» была недостижима, а администратор мог только продиктовать
временный пароль.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.password_reset import PasswordResetToken
from app.models.user import UserRole


def _create_link(client, headers, user_id):
    return client.post(f"/admin/users/{user_id}/reset-link", headers=headers, json={})


def _user_with_email(make_user, db, email="reset-link@example.test"):
    user, _headers = make_user()
    user.email = email
    db.commit()
    return user


def test_admin_issues_a_working_one_time_link(client, admin_headers, make_user, db):
    user = _user_with_email(make_user, db)
    created = _create_link(client, admin_headers, user.id)
    assert created.status_code == 200, created.text
    payload = created.json()
    assert "/reset-password?token=" in payload["url"]
    assert payload["ttl_hours"] == 24
    assert payload["expires_at"]

    token = payload["url"].split("token=", 1)[1]
    # В базе лежит только хеш: по самой ссылке строку не найти.
    stored = db.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)).all()
    assert len(stored) == 1 and token not in stored[0].token_hash

    reset = client.post("/auth/reset-password/confirm", json={
        "token": token, "new_password": "brand-new-pass-123", "confirm_password": "brand-new-pass-123"})
    assert reset.status_code == 200, reset.text

    login = client.post("/auth/token", data={"username": user.email, "password": "brand-new-pass-123"})
    assert login.status_code == 200, login.text

    # Второй раз та же ссылка не работает.
    again = client.post("/auth/reset-password/confirm", json={
        "token": token, "new_password": "another-pass-123", "confirm_password": "another-pass-123"})
    assert again.status_code == 400, again.text


def test_new_link_cancels_the_previous_one(client, admin_headers, make_user, db):
    user, _headers = make_user()
    first = _create_link(client, admin_headers, user.id).json()["url"].split("token=", 1)[1]
    second = _create_link(client, admin_headers, user.id).json()["url"].split("token=", 1)[1]
    assert first != second

    old = client.post("/auth/reset-password/confirm", json={
        "token": first, "new_password": "old-link-pass-123", "confirm_password": "old-link-pass-123"})
    assert old.status_code == 400, "старая ссылка должна быть погашена"

    fresh = client.post("/auth/reset-password/confirm", json={
        "token": second, "new_password": "new-link-pass-123", "confirm_password": "new-link-pass-123"})
    assert fresh.status_code == 200, fresh.text

    active = db.scalars(select(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))).all()
    assert active == [], "действующих ссылок после смены пароля остаться не должно"


def test_expired_link_is_rejected(client, admin_headers, make_user, db):
    user, _headers = make_user()
    token = _create_link(client, admin_headers, user.id).json()["url"].split("token=", 1)[1]
    row = db.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    expired = client.post("/auth/reset-password/confirm", json={
        "token": token, "new_password": "expired-pass-123", "confirm_password": "expired-pass-123"})
    assert expired.status_code == 400, expired.text


def test_stale_rows_are_purged_and_old_admins_cannot_touch_superadmin(client, admin_headers, make_user, db):
    user, _headers = make_user()
    _create_link(client, admin_headers, user.id)
    db.commit()

    # Старая использованная запись старше срока хранения должна исчезнуть при
    # следующем выпуске: иначе таблица растёт вечно.
    old = PasswordResetToken(user_id=user.id, token_hash=uuid.uuid4().hex,
                             expires_at=datetime.now(timezone.utc) - timedelta(days=90),
                             used_at=datetime.now(timezone.utc) - timedelta(days=60),
                             created_at=datetime.now(timezone.utc) - timedelta(days=90))
    db.add(old)
    db.commit()
    old_id = old.id

    _create_link(client, admin_headers, user.id)
    db.commit()
    db.expire_all()
    assert db.get(PasswordResetToken, old_id) is None

    superadmin, _ = make_user(UserRole.superadmin)
    # `admin_headers` — обычный администратор: трогать суперадмина он не может.
    denied = _create_link(client, admin_headers, superadmin.id)
    assert denied.status_code == 403, denied.text


def test_archived_user_gets_no_link(client, admin_headers, make_user, db):
    user, _headers = make_user()
    user.is_archived = True
    db.commit()
    response = _create_link(client, admin_headers, user.id)
    assert response.status_code == 409, response.text


def test_audit_records_the_event_without_the_token(client, admin_headers, make_user, db):
    from app.models.security_audit import SecurityAuditEvent

    user, _headers = make_user()
    token = _create_link(client, admin_headers, user.id).json()["url"].split("token=", 1)[1]
    events = db.scalars(select(SecurityAuditEvent).where(
        SecurityAuditEvent.event_type == "admin_reset_link_created")).all()
    assert events, "выдача ссылки должна попадать в аудит"
    meta = " ".join(str(event.meta or "") for event in events)
    assert token not in meta, "токен не должен попадать в аудит"
