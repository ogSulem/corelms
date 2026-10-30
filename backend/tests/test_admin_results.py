"""Экран «Результаты»: сводка считается по правилам прогресса ученика."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.attempt import QuizAttempt
from app.models.user import User, UserRole


def _learner(db, name="Ученик"):
    user = User(name=f"{name}-{uuid.uuid4().hex[:6]}", role=UserRole.employee, password_hash="x")
    db.add(user)
    db.commit()
    return user


def test_results_overview_counts_started_completed_and_attempts(client, db, admin_headers, make_module):
    module_a, lesson_a, quiz_a = make_module(required=True)
    module_b, _lesson_b, _quiz_b = make_module(required=True)
    learner = _learner(db)

    # Модуль A: пройден урок и тест; модуль B: ни одного действия.
    db.add(QuizAttempt(user_id=learner.id, quiz_id=quiz_a.id, score=90, passed=True,
                       started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc)))
    db.commit()

    response = client.get("/admin/analytics/overview", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()

    totals = body["totals"]
    assert totals["users"] >= 1 and totals["modules"] >= 2
    assert totals["completions"] >= 1
    assert totals["attempts"] >= 1 and totals["pass_rate"] == 100

    rows = {row["id"]: row for row in body["modules"]}
    assert rows[str(module_a.id)]["started"] == 1
    assert rows[str(module_a.id)]["completed"] == 1
    assert rows[str(module_a.id)]["avg_percent"] == 100
    assert rows[str(module_a.id)]["attempts"] == 1 and rows[str(module_a.id)]["avg_score"] == 90
    assert rows[str(module_b.id)]["started"] == 0 and rows[str(module_b.id)]["avg_percent"] == 0

    person = {row["id"]: row for row in body["users"]}[str(learner.id)]
    assert person["completed"] == 1 and person["attempts"] == 1 and person["avg_score"] == 90


def test_results_overview_is_admin_only(client, make_user):
    employee = make_user(UserRole.employee)[1]
    assert client.get("/admin/analytics/overview", headers=employee).status_code == 403


def test_users_list_exposes_email_for_the_admin_screen(client, db, admin_headers):
    user = User(name="Почтовый", email=f"mail-{uuid.uuid4().hex[:6]}@example.com",
                role=UserRole.employee, password_hash="x")
    db.add(user)
    db.commit()

    response = client.get("/admin/users", headers=admin_headers)
    assert response.status_code == 200, response.text
    row = {item["id"]: item for item in response.json()["items"]}[str(user.id)]
    assert row["email"] == user.email


def test_admin_users_list_survives_odd_rows(client, db, admin_headers, make_user):
    """Список сотрудников не должен падать 500 из-за одной странной записи."""
    from sqlalchemy import select

    from app.models.tag import Tag, UserTagMap
    from app.models.user import User

    make_user()
    tag = Tag(name="Отдел без сотрудников")
    db.add(tag)
    db.flush()
    someone = db.scalar(select(User).limit(1))
    assert someone is not None
    db.add(UserTagMap(user_id=someone.id, tag_id=tag.id))
    db.commit()

    response = client.get("/admin/users", headers=admin_headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items
    assert all("progress_summary" in item for item in items)
    assert all(isinstance(item["role"], str) and item["role"] for item in items)
    assert all(isinstance(item["tags"], list) for item in items)


def test_results_overview_separates_completions_from_module_count(client, db, admin_headers, make_module):
    """Завершения — пары «человек × модуль»: их больше, чем модулей.

    На экране «Результаты» цифра стояла рядом с «из 40 опубликованных» и читалась
    как «167 из 40». Поэтому рядом с суммой отдаём охват и число людей.
    """
    module_a, _lesson_a, quiz_a = make_module(required=True)
    module_b, _lesson_b, quiz_b = make_module(required=True)
    first = _learner(db, "Первый")
    second = _learner(db, "Второй")

    for learner, quiz in ((first, quiz_a), (second, quiz_a), (second, quiz_b)):
        db.add(QuizAttempt(user_id=learner.id, quiz_id=quiz.id, score=100, passed=True,
                           started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc)))
    db.commit()

    totals = client.get("/admin/analytics/overview", headers=admin_headers).json()["totals"]

    assert totals["completions"] == 3            # три пары «человек × модуль»
    assert totals["learners_completed"] == 2     # но всего два человека
    assert totals["modules_completed"] == 2      # и два модуля
    assert totals["published"] >= 2
    assert 0 <= totals["completion_rate"] <= 100


def test_superadmin_can_switch_a_user_to_partner(client, db, make_user):
    """Роль partner должна приниматься API, а не только показываться в списке."""
    employee = make_user(UserRole.employee)[0]
    superadmin_headers = make_user(UserRole.superadmin)[1]

    response = client.patch(f"/admin/users/{employee.id}", headers=superadmin_headers, json={"role": "partner"})
    assert response.status_code == 200, response.text

    db.expire_all()
    updated = db.get(User, employee.id)
    assert updated is not None and updated.role == UserRole.partner


def test_admin_creates_and_deletes_tags(client, db, admin_headers, make_user):
    """Кнопка «Теги» на экране пользователей: создание и удаление через API."""
    from app.models.tag import Tag, UserTagMap

    created = client.post("/admin/tags", headers=admin_headers, json={"name": "Смены ночью"})
    assert created.status_code == 200, created.text
    tag_id = created.json()["id"]
    assert created.json()["name"] == "Смены ночью"

    # Повторное создание не плодит дубли и возвращает тот же тег.
    again = client.post("/admin/tags", headers=admin_headers, json={"name": "  смены НОЧЬЮ "})
    assert again.json()["id"] == tag_id

    employee, employee_headers = make_user(UserRole.employee)
    db.add(UserTagMap(user_id=employee.id, tag_id=__import__("uuid").UUID(tag_id)))
    db.commit()

    deleted = client.delete(f"/admin/tags/{tag_id}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text
    db.expire_all()
    assert db.get(Tag, __import__("uuid").UUID(tag_id)) is None
    assert db.scalar(select(UserTagMap).where(UserTagMap.user_id == employee.id)) is None

    # Ученик не может управлять тегами.
    assert client.post("/admin/tags", headers=employee_headers, json={"name": "Свои"}).status_code == 403
