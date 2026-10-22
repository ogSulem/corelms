import uuid
from datetime import datetime

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.asset import ContentAsset
from app.models.attempt import QuizAttempt, QuizAttemptAnswer
from app.models.audit import LearningEvent, LearningEventType
from app.models.completion import LessonQuizVersion
from app.models.module import Module, Submodule
from app.models.quiz import Question, Quiz, QuizType
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.user import User


def start(client, headers, lesson, quiz):
    assert client.post(f"/submodules/{lesson.id}/read", headers=headers).status_code == 200
    response = client.post(f"/quizzes/{quiz.id}/start", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def submit(client, headers, quiz_id, session, answer="A"):
    response = client.post(f"/quizzes/{quiz_id}/submit", headers=headers,
                           json={"session_id": session["session_id"], "answers": [{"question_id": q["id"], "answer": answer} for q in session["questions"]]})
    assert response.status_code == 200, response.text
    return response.json()


def test_server_session_denominator_and_required_read(client, make_module, make_user):
    _, lesson, quiz = make_module(required=True, question_count=2)
    _, headers = make_user()
    assert client.post(f"/quizzes/{quiz.id}/start", headers=headers).status_code == 403
    assert client.post(f"/quizzes/{quiz.id}/submit", headers=headers, json={"answers": []}).status_code == 409
    session = start(client, headers, lesson, quiz)
    # Sending only the one known answer cannot turn a 2-question quiz into 100%.
    response = client.post(f"/quizzes/{quiz.id}/submit", headers=headers,
                           json={"session_id": session["session_id"], "answers": [{"question_id": session["questions"][0]["id"], "answer": "A"}]})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2 and response.json()["score"] == 50
    assert not response.json()["passed"]


def test_submit_retry_is_durable_and_does_not_award_xp_twice(client, make_module, make_user, redis_memory):
    module, lesson, quiz = make_module(required=True)
    user, headers = make_user()
    session = start(client, headers, lesson, quiz)
    first = submit(client, headers, quiz.id, session)
    assert first["passed"] and first["xp_awarded"] == 25
    with SessionLocal() as db:
        before = db.get(User, user.id).xp
    # Lose all ephemeral quiz/cache state while keeping the login session.
    # A total Redis reset correctly requires a new login; quiz results remain in SQL.
    for key in redis_memory.scan_iter():
        if not key.startswith("auth:"):
            redis_memory.delete(key)
    second = submit(client, headers, quiz.id, session, answer="B")
    assert second["replayed"] and second["score"] == first["score"]
    with SessionLocal() as db:
        assert db.get(User, user.id).xp == before
        assert db.scalar(select(func.count()).select_from(QuizAttempt).where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user.id)) == 1
    assert client.get(f"/progress/modules/{module.id}", headers=headers).json()["completed"]


def test_question_edit_versions_quiz_and_inflight_attempts(client, db, admin_headers, make_module, make_user):
    module, lesson, quiz = make_module(required=True)
    learner, headers = make_user()
    session = start(client, headers, lesson, quiz)
    old_question_id = session["questions"][0]["id"]
    response = client.patch(f"/admin/questions/{old_question_id}", headers=admin_headers,
                            json={"prompt": "Изменённый вопрос\nA) Неверно\nB) Верно", "correct_answer": "B"})
    assert response.status_code == 200, response.text
    edited = response.json()["item"]
    new_quiz_id = edited["quiz_id"]
    assert new_quiz_id != str(quiz.id)
    assert edited["id"] != old_question_id
    resumed = client.post(f"/quizzes/{quiz.id}/start", headers=headers)
    assert resumed.status_code == 200 and resumed.json()["session_id"] == session["session_id"]
    assert submit(client, headers, quiz.id, session, answer="A")["passed"]
    # There is no new start on the retired quiz once its session is submitted.
    assert client.post(f"/quizzes/{quiz.id}/start", headers=headers).status_code == 409
    db.expire_all()
    assert db.get(Question, uuid.UUID(old_question_id)).correct_answer == "A"
    assert db.get(LessonQuizVersion, quiz.id).submodule_id == lesson.id
    assert db.get(Submodule, lesson.id).quiz_id == uuid.UUID(new_quiz_id)
    progress = client.get(f"/progress/modules/{module.id}", headers=headers).json()
    assert progress["submodules"][0]["passed"] and progress["completed"]
    new_session = client.post(f"/quizzes/{new_quiz_id}/start", headers=headers).json()
    assert submit(client, headers, new_quiz_id, new_session, answer="B")["xp_awarded"] == 0
    with SessionLocal() as check:
        answer = check.scalar(select(QuizAttemptAnswer).where(QuizAttemptAnswer.question_id == uuid.UUID(old_question_id)))
        assert answer and answer.answer == "A" and answer.is_correct


def test_question_delete_retains_old_answers_and_rejects_stale_edits(client, db, admin_headers, make_module, make_user):
    _, lesson, quiz = make_module(required=True, question_count=2)
    _, headers = make_user()
    session = start(client, headers, lesson, quiz)
    submit(client, headers, quiz.id, session)
    original_id = session["questions"][0]["id"]
    response = client.delete(f"/admin/questions/{original_id}", headers=admin_headers)
    assert response.status_code == 200, response.text
    new_quiz = response.json()["quiz_id"]
    db.expire_all()
    assert db.get(Question, uuid.UUID(original_id)) is not None
    assert db.scalar(select(func.count()).select_from(QuizAttemptAnswer).where(QuizAttemptAnswer.question_id == uuid.UUID(original_id))) == 1
    stale = client.patch(f"/admin/questions/{original_id}", headers=admin_headers, json={"correct_answer": "B"})
    assert stale.status_code == 409
    remaining = db.scalar(select(Question).where(Question.quiz_id == uuid.UUID(new_quiz)))
    assert client.delete(f"/admin/questions/{remaining.id}", headers=admin_headers).status_code == 409


def test_admin_can_prepare_questions_before_enabling_quiz(client, db, admin_headers, make_module):
    module, lesson, quiz = make_module(required=False, question_count=0)
    response = client.post("/admin/questions", headers=admin_headers,
                           json={"quiz_id": str(quiz.id), "type": "single", "prompt": "Готовый вопрос\nA) Да\nB) Нет", "correct_answer": "A"})
    assert response.status_code == 200, response.text
    current = client.get(f"/admin/content/modules/{module.id}", headers=admin_headers).json()
    enabled = client.patch(f"/admin/content/modules/{module.id}/lessons/{lesson.id}", headers=admin_headers,
                           json={"revision": current["module"]["content_revision"], "requires_quiz": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["lessons"][0]["requires_quiz"]


def test_final_requires_read_only_lessons_too_and_reuses_session(client, db, make_module, make_user):
    module, required, quiz = make_module(required=True, final=True)
    spare_quiz = Quiz(type=QuizType.submodule)
    db.add(spare_quiz)
    db.flush()
    reading = Submodule(module_id=module.id, title="Обязательное прочтение", order=2, quiz_id=spare_quiz.id, requires_quiz=False, content="Инструкция")
    db.add(reading)
    db.commit()
    _, headers = make_user()
    session = start(client, headers, required, quiz)
    submit(client, headers, quiz.id, session)
    assert client.post(f"/quizzes/{module.final_quiz_id}/start", headers=headers).status_code == 403
    client.post(f"/submodules/{reading.id}/read", headers=headers)
    first = client.post(f"/quizzes/{module.final_quiz_id}/start", headers=headers)
    second = client.post(f"/quizzes/{module.final_quiz_id}/start", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["session_id"] == second.json()["session_id"]
    assert first.json()["questions"] == second.json()["questions"]
    assert len(first.json()["questions"]) == 1  # The last quiz-bearing lesson is not silently excluded.
    submit(client, headers, module.final_quiz_id, first.json())
    assert client.get(f"/progress/modules/{module.id}", headers=headers).json()["completed"]


def test_redis_unavailable_does_not_allow_client_selected_questions(client, make_module, make_user, monkeypatch):
    import app.routers.quizzes as quizzes
    _, lesson, quiz = make_module(required=True)
    _, headers = make_user()
    session = start(client, headers, lesson, quiz)
    def unavailable():
        raise ConnectionError("redis offline")
    monkeypatch.setattr(quizzes, "get_redis", unavailable)
    assert client.post(f"/quizzes/{quiz.id}/start", headers=headers).status_code == 503
    response = client.post(f"/quizzes/{quiz.id}/submit", headers=headers,
                           json={"session_id": session["session_id"], "answers": []})
    assert response.status_code == 503


def test_legacy_json_read_is_idempotent_and_counts_in_progress(client, db, make_module, make_user):
    module, lesson, _ = make_module(required=False)
    learner, headers = make_user()
    db.add(LearningEvent(user_id=learner.id, type=LearningEventType.submodule_opened, ref_id=lesson.id, meta='{"action": "read", "version": 1}'))
    db.commit()
    response = client.post(f"/submodules/{lesson.id}/read", headers=headers)
    assert response.status_code == 200 and response.json()["xp_awarded"] == 0
    progress = client.get(f"/progress/modules/{module.id}", headers=headers).json()
    assert progress["completed"] and progress["submodules"][0]["read"]
    assert progress["completed_at"] is not None


def test_empty_or_archived_file_only_module_never_auto_completes(client, db, make_module, make_user):
    module, folder, _ = make_module(folder=True, question_count=0)
    learner, headers = make_user()
    client.post(f"/modules/{module.id}/open", headers=headers)
    assert not client.get(f"/progress/modules/{module.id}", headers=headers).json()["completed"]
    folder.is_archived = True
    asset = ContentAsset(module_id=module.id, bucket="testing", object_key=f"module/{module.id}/hidden", original_filename="hidden.pdf")
    db.add(asset)
    db.flush()
    db.add(SubmoduleAssetMap(submodule_id=folder.id, asset_id=asset.id, order=1))
    db.commit()
    assert not client.get(f"/progress/modules/{module.id}", headers=headers).json()["completed"]


def test_old_attempt_keeps_history_context_after_question_replacement(client, db, admin_headers, make_module, make_user):
    module, lesson, quiz = make_module(required=True)
    _, headers = make_user()
    session = start(client, headers, lesson, quiz)
    submit(client, headers, quiz.id, session)
    question = db.scalar(select(Question).where(Question.quiz_id == quiz.id))
    changed = client.patch(f"/admin/questions/{question.id}", headers=admin_headers, json={"prompt": "Новая формулировка\nA) Верно\nB) Неверно"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["item"]["quiz_id"] != str(quiz.id)
    history = client.get("/me/history", headers=headers)
    assert history.status_code == 200, history.text
    old = next(item for item in history.json()["items"] if item["kind"] == "quiz_attempt")
    assert old["module_id"] == str(module.id) and old["submodule_id"] == str(lesson.id)
    recent = client.get("/me/recent-activity", headers=headers)
    assert recent.status_code == 200, recent.text
    assert recent.json()["attempts"][0]["submodule_id"] == str(lesson.id)


def test_parallel_start_and_submit_are_idempotent_on_postgres(client, db, make_module, make_user):
    import pytest
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    if db.bind.dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency requires PostgreSQL")
    _, lesson, quiz = make_module(required=True)
    user, headers = make_user()
    client.post(f"/submodules/{lesson.id}/read", headers=headers)
    gate = Barrier(2)
    def starting():
        gate.wait(timeout=10)
        response = client.post(f"/quizzes/{quiz.id}/start", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        sessions = list(pool.map(lambda _: starting(), range(2)))
    assert sessions[0]["session_id"] == sessions[1]["session_id"]
    gate = Barrier(2)
    def finishing():
        gate.wait(timeout=10)
        return submit(client, headers, quiz.id, sessions[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: finishing(), range(2)))
    assert sorted(result["replayed"] for result in results) == [False, True]
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(QuizAttempt).where(QuizAttempt.user_id == user.id, QuizAttempt.quiz_id == quiz.id)) == 1
    assert db.get(User, user.id).xp == 30  # Read=5, single mastery=25.
