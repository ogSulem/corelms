"""Удаление пользователя: архив с сохранением истории и «пустое» удаление.

Раньше `DELETE /admin/users/{id}` падал с 500 на любом пользователе, которому
выдали тег: строка `user_tag_map` оставалась, и Postgres отказывал по внешнему
ключу (`IntegrityError: FOREIGN KEY constraint failed`). Плюс само удаление
стирало попытки тестов и прогресс — это противоречит правилу платформы
(«история ученика не удаляется»).

Теперь обычный DELETE — это архив: вход закрывается, из списков человек
исчезает, история остаётся. Окончательное удаление разрешено только для
учётной записи без истории и обязано убирать все ссылки на `users.id`.
"""

import uuid

from sqlalchemy import select

from app.models.attempt import QuizAttempt
from app.models.tag import Tag, UserTagMap
from app.models.user import User, UserRole


def _create_partner_via_admin(client, superadmin_headers, *, email: str, tag_id: str | None = None):
    response = client.post(
        "/admin/users",
        headers=superadmin_headers,
        json={"name": "Партнёр Тестовый", "email": email, "position": "Менеджер"},
    )
    assert response.status_code in (200, 201), response.text
    payload = response.json()
    user_id = payload["id"]
    if tag_id:
        tagged = client.put(f"/admin/users/{user_id}/tags", headers=superadmin_headers,
                            json={"tag_ids": [tag_id]})
        assert tagged.status_code == 200, tagged.text
    return user_id, payload["temp_password"]


def _tag(db) -> Tag:
    tag = Tag(name=f"Тег {uuid.uuid4().hex[:6]}")
    db.add(tag)
    db.commit()
    return tag


def _attempt_for(db, user_id: uuid.UUID) -> QuizAttempt:
    """Настоящая попытка теста: создаём минимальный квиз, чтобы внешний ключ был валиден."""
    from app.models.quiz import Quiz, QuizType

    quiz = Quiz(type=QuizType.submodule, pass_threshold=70, attempts_limit=3)
    db.add(quiz)
    db.flush()
    attempt = QuizAttempt(quiz_id=quiz.id, user_id=user_id, attempt_no=1, score=80, passed=True)
    db.add(attempt)
    db.commit()
    return attempt


def _login(client, email: str, password: str):
    return client.post(
        "/auth/token",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def test_delete_archives_tagged_user_and_keeps_history(db, client, make_user):
    _, superadmin_headers = make_user(UserRole.superadmin)
    tag = _tag(db)
    user_id, password = _create_partner_via_admin(client, superadmin_headers, email="archive-me@example.com",
                                                 tag_id=str(tag.id))
    token = _login(client, "archive-me@example.com", password).json()["access_token"]
    live_headers = {"Authorization": f"Bearer {token}"}

    # У пользователя есть история: попытка теста (удалять такое нельзя).
    _attempt_for(db, uuid.UUID(user_id))

    response = client.delete(f"/admin/users/{user_id}", headers=superadmin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["archived"] is True

    db.expire_all()
    archived = db.scalar(select(User).where(User.id == uuid.UUID(user_id)))
    assert archived is not None, "архив не должен удалять запись"
    assert archived.is_archived is True
    # История на месте.
    assert db.scalar(select(QuizAttempt).where(QuizAttempt.user_id == archived.id)) is not None
    # Тег остался привязан — история и права вернутся при восстановлении.
    assert db.scalar(select(UserTagMap).where(UserTagMap.user_id == archived.id)) is not None

    # Из списка исчез, в архивном списке — есть и помечен.
    listing = client.get("/admin/users", headers=superadmin_headers)
    assert listing.status_code == 200
    assert all(item["id"] != user_id for item in listing.json()["items"])
    archived_listing = client.get("/admin/users?include_archived=true", headers=superadmin_headers)
    shown = next(item for item in archived_listing.json()["items"] if item["id"] == user_id)
    assert shown["is_archived"] is True

    # Вход закрыт, ранее выданный токен больше не работает.
    assert _login(client, "archive-me@example.com", password).status_code == 403
    assert client.get("/auth/me", headers=live_headers).status_code == 401

    # Восстановление возвращает доступ.
    restored = client.post(f"/admin/users/{user_id}/restore", headers=superadmin_headers)
    assert restored.status_code == 200, restored.text
    assert _login(client, "archive-me@example.com", password).status_code == 200


def test_permanent_delete_removes_tag_rows(db, client, make_user):
    """Регрессия: раньше это падало на внешнем ключе user_tag_map."""
    _, superadmin_headers = make_user(UserRole.superadmin)
    tag = _tag(db)
    user_id, _ = _create_partner_via_admin(client, superadmin_headers, email="purge-me@example.com",
                                           tag_id=str(tag.id))

    response = client.delete(f"/admin/users/{user_id}?permanent=true", headers=superadmin_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "archived": False, "deleted": True}

    db.expire_all()
    uid = uuid.UUID(user_id)
    assert db.scalar(select(User).where(User.id == uid)) is None
    assert db.scalar(select(UserTagMap).where(UserTagMap.user_id == uid)) is None
    # Тег как справочник не удаляется вместе с человеком.
    assert db.scalar(select(Tag).where(Tag.id == tag.id)) is not None


def test_permanent_delete_is_refused_when_history_exists(db, client, make_user):
    _, superadmin_headers = make_user(UserRole.superadmin)
    user_id, _ = _create_partner_via_admin(client, superadmin_headers, email="has-history@example.com")
    _attempt_for(db, uuid.UUID(user_id))

    response = client.delete(f"/admin/users/{user_id}?permanent=true", headers=superadmin_headers)
    assert response.status_code == 409, response.text
    assert "архив" in response.json()["error_message"].lower()

    db.expire_all()
    assert db.scalar(select(User).where(User.id == uuid.UUID(user_id))) is not None


def test_admin_cannot_archive_another_admin(db, client, make_user):
    _, admin_headers = make_user(UserRole.admin)
    victim, _ = make_user(UserRole.admin)

    response = client.delete(f"/admin/users/{victim.id}", headers=admin_headers)
    assert response.status_code == 403, response.text
