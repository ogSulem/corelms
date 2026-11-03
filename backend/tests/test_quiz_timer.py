"""Таймер теста должен реально ограничивать попытку.

Что было сломано (проверено на живом запросе до правки):

* `/submit` после истечения отвечал 409 `time limit exceeded` — ответы просто
  пропадали;
* `/start` после истечения молча создавал новую сессию с новым таймером,
  не записывая попытку: `attempt_no` оставался 1, попыток в базе — 0.

То есть таймер был декорацией, а попытки не расходовались. Теперь:

* ответы, отправленные в пределах 30 секунд после нуля (автоотправка с
  клиента), принимаются, время записывается ровно как лимит;
* брошенная попытка закрывается при следующем `/start` как непройденная и
  расходует лимит;
* у ошибок есть машинные коды (`time_limit_exceeded`, `quiz_session_missing`,
  `attempts_exhausted`), по которым интерфейс показывает понятный текст.
"""

import json
import time
import uuid

from sqlalchemy import select

from app.models.attempt import QuizAttempt
from app.models.audit import LearningEvent, LearningEventType
from app.routers import quizzes as quizzes_module


def _learner_with_read(db, make_user, make_module, *, attempts_limit=3, time_limit=60):
    user, headers = make_user()
    module, lesson, quiz = make_module(required=True)
    quiz.time_limit = time_limit
    quiz.attempts_limit = attempts_limit
    db.add(LearningEvent(user_id=user.id, type=LearningEventType.submodule_opened, ref_id=lesson.id, meta="read"))
    db.commit()
    return user, headers, module, lesson, quiz


def _shift_session(user_id, quiz_id, seconds_ago: int):
    """Сдвинуть серверную сессию теста в прошлое — так «проходит» время."""
    from app.core.redis_client import get_redis
    key = f"quiz_session:{user_id}:{quiz_id}"
    raw = get_redis().get(key)
    assert raw, "сессия теста должна существовать"
    session = json.loads(raw)
    session["started_at"] = int(time.time()) - seconds_ago
    get_redis().set(key, json.dumps(session), ex=3600)
    return session


def test_expired_attempt_is_closed_and_counted(db, client, make_user, make_module):
    user, headers, module, lesson, quiz = _learner_with_read(db, make_user, make_module)

    started = client.post(f"/quizzes/{quiz.id}/start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json()["attempt_no"] == 1

    _shift_session(user.id, quiz.id, seconds_ago=600)

    # Вторая попытка: истёкшая закрывается, лимит расходуется.
    again = client.post(f"/quizzes/{quiz.id}/start", headers=headers)
    assert again.status_code == 200, again.text
    assert again.json()["attempt_no"] == 2

    db.expire_all()
    attempts = db.scalars(select(QuizAttempt).where(QuizAttempt.user_id == user.id, QuizAttempt.quiz_id == quiz.id)).all()
    assert len(attempts) == 1, "брошенная попытка должна быть записана"
    assert attempts[0].score == 0 and attempts[0].passed is False and attempts[0].xp_awarded == 0
    assert attempts[0].time_spent_seconds == quiz.time_limit


def test_submit_just_after_the_limit_is_accepted(db, client, make_user, make_module):
    """Автоотправка приходит через секунду после нуля — ответы не должны пропадать."""
    user, headers, module, lesson, quiz = _learner_with_read(db, make_user, make_module, time_limit=60)
    started = client.post(f"/quizzes/{quiz.id}/start", headers=headers).json()

    _shift_session(user.id, quiz.id, seconds_ago=quiz.time_limit + 5)

    response = client.post(
        f"/quizzes/{quiz.id}/submit",
        headers=headers,
        json={"session_id": started["session_id"],
              "answers": [{"question_id": started["questions"][0]["id"], "answer": "A"}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["score"] == 100 and body["passed"] is True
    assert body["total"] == 1

    db.expire_all()
    attempt = db.scalar(select(QuizAttempt).where(QuizAttempt.user_id == user.id, QuizAttempt.quiz_id == quiz.id))
    assert attempt is not None
    assert attempt.time_spent_seconds == quiz.time_limit, "время не должно превышать лимит"


def test_submit_well_after_the_limit_has_a_machine_code(db, client, make_user, make_module):
    user, headers, module, lesson, quiz = _learner_with_read(db, make_user, make_module, time_limit=60)
    started = client.post(f"/quizzes/{quiz.id}/start", headers=headers).json()

    _shift_session(user.id, quiz.id, seconds_ago=quiz.time_limit + 600)
    response = client.post(
        f"/quizzes/{quiz.id}/submit",
        headers=headers,
        json={"session_id": started["session_id"],
              "answers": [{"question_id": started["questions"][0]["id"], "answer": "A"}]},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "time_limit_exceeded"

    db.expire_all()
    assert db.scalar(select(QuizAttempt).where(QuizAttempt.user_id == user.id)) is None


def test_attempts_exhausted_has_a_machine_code(db, client, make_user, make_module):
    user, headers, module, lesson, quiz = _learner_with_read(db, make_user, make_module, attempts_limit=1)
    db.add(QuizAttempt(quiz_id=quiz.id, user_id=user.id, attempt_no=1, score=0, passed=False))
    db.commit()

    response = client.post(f"/quizzes/{quiz.id}/start", headers=headers)
    assert response.status_code == 409
    assert response.json()["error_code"] == "attempts_exhausted"


def test_grace_constant_is_small_enough_not_to_cover_a_second_attempt():
    """Запас на отправку не должен превращаться в новый таймер."""
    assert 0 < quizzes_module.SESSION_GRACE_SECONDS <= 60
