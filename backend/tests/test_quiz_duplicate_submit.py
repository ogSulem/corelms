"""Одновременная отправка теста не должна давать 500 и вторую попытку.

Уникальный `session_id` защищает от дубля в базе, но до этой правки гонка двух
запросов (двойной клик, повтор после таймаута) заканчивалась ошибкой 500: второй
запрос вставлял ту же попытку и падал на ограничении. Теперь проигравший гонку
откатывается целиком и отдаёт сохранённый результат первой попытки.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.attempt import QuizAttempt
from app.models.audit import LearningEvent, LearningEventType
from app.models.user import User


def _start(client, headers, lesson, quiz):
    assert client.post(f"/submodules/{lesson.id}/read", headers=headers).status_code == 200
    response = client.post(f"/quizzes/{quiz.id}/start", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _payload(session):
    return {"session_id": session["session_id"],
            "answers": [{"question_id": q["id"], "answer": "A"} for q in session["questions"]]}


def test_concurrent_duplicate_submit_is_not_a_server_error(client, make_module, make_user, monkeypatch,
                                                          redis_memory):
    module, lesson, quiz = make_module(required=True)
    user, headers = make_user()
    session = _start(client, headers, lesson, quiz)

    from app.routers import quizzes as quizzes_router
    key = quizzes_router._session_key(str(user.id), str(quiz.id))
    snapshot = redis_memory.get(key)
    assert snapshot, "сессия теста должна лежать в Redis"
    original = quizzes_router._submitted_result
    monkeypatch.setattr(quizzes_router, "_submitted_result", lambda *args, **kwargs: None)

    first = client.post(f"/quizzes/{quiz.id}/submit", headers=headers, json=_payload(session))
    assert first.status_code == 200, first.text
    with SessionLocal() as db:
        xp_after_first = db.get(User, user.id).xp
        assert xp_after_first > 0
    # Восстанавливаем сессию в Redis: при настоящей гонке оба запроса успевают
    # прочитать её до удаления, а второй «не видит» сохранённый результат и
    # упирается в уникальность session_id.
    redis_memory.set(key, snapshot)
    second = client.post(f"/quizzes/{quiz.id}/submit", headers=headers, json=_payload(session))
    assert second.status_code != 500, second.text
    assert second.status_code == 409, second.text
    assert second.json()["error_code"] == "attempt_already_finished"

    monkeypatch.setattr(quizzes_router, "_submitted_result", original)
    with SessionLocal() as db:
        attempts = db.scalar(select(func.count()).select_from(QuizAttempt)
                             .where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user.id))
        assert attempts == 1
        events = db.scalar(select(func.count()).select_from(LearningEvent)
                           .where(LearningEvent.user_id == user.id,
                                  LearningEvent.type == LearningEventType.quiz_completed))
        assert events == 1
        xp = db.get(User, user.id).xp
    # XP и событие не задвоились.
    assert xp == xp_after_first


def test_duplicate_submit_returns_the_same_result_when_race_is_lost(client, make_module, make_user):
    """Если результат уже виден в базе, повтор возвращает его, а не ошибку."""
    module, lesson, quiz = make_module(required=True)
    user, headers = make_user()
    session = _start(client, headers, lesson, quiz)
    first = client.post(f"/quizzes/{quiz.id}/submit", headers=headers, json=_payload(session))
    assert first.status_code == 200, first.text
    again = client.post(f"/quizzes/{quiz.id}/submit", headers=headers, json=_payload(session))
    assert again.status_code == 200, again.text
    assert again.json()["replayed"] is True
    assert again.json()["score"] == first.json()["score"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(QuizAttempt)
                         .where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user.id)) == 1
