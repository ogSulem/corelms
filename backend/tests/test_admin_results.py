"""Экран «Результаты»: сводка считается по правилам прогресса ученика."""

import uuid
from datetime import datetime, timezone

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
