"""Бюджет SQL-запросов: число запросов не должно расти вместе с данными.

N+1 не виден на маленькой тестовой базе: страница отвечает быстро, а на проде
с сотней уроков и тысячей пользователей превращается в сотни запросов. Поэтому
сравниваем число запросов на маленьком и на большом наборе — оно обязано
совпадать, а абсолютное значение держим в явном бюджете.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.models.asset import ContentAsset
from app.models.module import Submodule
from app.models.quiz import Quiz, QuizType
from app.models.user import User, UserRole


@pytest.fixture()
def query_counter():
    """Счётчик SQL-запросов через тот же движок, что у приложения в тестах."""
    from app.db import session as session_module

    engine = session_module.engine
    state = {"n": 0}

    def before(*_args, **_kwargs):
        state["n"] += 1

    def measure(call):
        state["n"] = 0
        event.listen(engine, "before_cursor_execute", before)
        try:
            response = call()
        finally:
            event.remove(engine, "before_cursor_execute", before)
        return state["n"], response

    return measure


def _add_lessons(db, module, quiz, count: int) -> None:
    for index in range(count):
        own_quiz = Quiz(type=QuizType.submodule, pass_threshold=70, attempts_limit=3)
        db.add(own_quiz)
        db.flush()
        db.add(
            Submodule(
                module_id=module.id,
                title=f"Урок {index + 2}",
                order=index + 2,
                quiz_id=own_quiz.id,
                requires_quiz=True,
                content=f"текст урока {index}",
            )
        )
        db.add(
            ContentAsset(
                module_id=module.id,
                object_key=f"uploads/sources/file-{index}.pdf",
                bucket="testing",
                original_filename=f"file-{index}.pdf",
                mime_type="application/pdf",
                size_bytes=1024,
            )
        )
    db.commit()


def test_module_page_queries_do_not_grow_with_lessons(client, db, make_module, auth_headers, query_counter):
    """Страница модуля и прогресс: 41 урок — столько же запросов, сколько один."""
    small, _lesson, _quiz = make_module(required=True)
    big, _big_lesson, big_quiz = make_module(required=True)
    _add_lessons(db, big, big_quiz, 40)

    small_submodules, response_small = query_counter(
        lambda: client.get(f"/modules/{small.id}/submodules", headers=auth_headers)
    )
    big_submodules, response_big = query_counter(
        lambda: client.get(f"/modules/{big.id}/submodules", headers=auth_headers)
    )
    assert response_small.status_code == response_big.status_code == 200
    assert big_submodules == small_submodules
    assert big_submodules <= 8, big_submodules

    small_progress, _ = query_counter(lambda: client.get(f"/progress/modules/{small.id}", headers=auth_headers))
    big_progress, response = query_counter(lambda: client.get(f"/progress/modules/{big.id}", headers=auth_headers))
    assert response.status_code == 200
    assert big_progress == small_progress
    assert big_progress <= 16, big_progress


def test_module_list_does_not_scale_with_module_count(client, db, make_module, auth_headers, query_counter):
    """Список модулей: 60 модулей — те же запросы, что и у одного."""
    make_module()
    one, response_one = query_counter(lambda: client.get("/modules/overview", headers=auth_headers))
    for _ in range(60):
        make_module()
    many, response_many = query_counter(lambda: client.get("/modules/overview", headers=auth_headers))

    assert response_one.status_code == response_many.status_code == 200
    assert many == one
    assert many <= 14, many


def test_admin_users_list_does_not_scale_with_user_count(client, db, admin_headers, query_counter):
    """Админка пользователей: 200 человек не должны добавлять запросов."""
    one, response_one = query_counter(lambda: client.get("/admin/users", headers=admin_headers))
    db.add_all([User(name=f"mass_{index}", role=UserRole.employee, password_hash="x") for index in range(200)])
    db.commit()
    many, response_many = query_counter(lambda: client.get("/admin/users", headers=admin_headers))

    assert response_one.status_code == response_many.status_code == 200
    assert many == one
    assert many <= 16, many


def test_lesson_page_does_not_scale_with_assets(client, db, make_module, auth_headers, query_counter):
    """Урок с 40 файлами: число запросов то же, что у урока без файлов."""
    module, lesson, _quiz = make_module(required=False)
    empty, response_empty = query_counter(
        lambda: client.get(f"/modules/submodules/{lesson.id}/assets", headers=auth_headers)
    )
    _add_lessons(db, module, _quiz, 40)
    loaded, response_loaded = query_counter(
        lambda: client.get(f"/modules/submodules/{lesson.id}/assets", headers=auth_headers)
    )

    assert response_empty.status_code == response_loaded.status_code == 200
    assert loaded == empty
    assert loaded <= 8, loaded


def _add_ready_lessons(db, module, count: int) -> None:
    """Уроки с текстом и готовым тестом: такие проходят проверку публикации."""
    from app.models.quiz import Question, QuestionType

    for index in range(count):
        quiz = Quiz(type=QuizType.submodule, pass_threshold=70, attempts_limit=3)
        db.add(quiz)
        db.flush()
        db.add(
            Submodule(
                module_id=module.id,
                title=f"Урок {index + 2}",
                order=index + 2,
                quiz_id=quiz.id,
                requires_quiz=True,
                content=f"текст урока {index}",
            )
        )
        db.add(
            Question(
                quiz_id=quiz.id,
                type=QuestionType.single,
                difficulty=1,
                prompt="Вопрос\nA) Верно\nB) Неверно",
                correct_answer="A",
                concept_tag="ok:test",
            )
        )
    db.commit()


def test_publish_check_does_not_scale_with_lessons(client, db, make_module, admin_headers, query_counter):
    """Публикация модуля: 41 урок — столько же запросов, сколько один.

    Проверка «можно ли опубликовать» раньше делала два запроса на каждый урок
    (файлы и вопросы) под блокировкой строки модуля: на большом модуле это
    десятки запросов, и они держали блокировку дольше, чем нужно.
    """
    small, _lesson, _quiz = make_module(required=True, active=False)
    big, _big_lesson, _big_quiz = make_module(required=True, active=False)
    _add_ready_lessons(db, big, 40)
    big_revision = int(big.content_revision)
    small_revision = int(small.content_revision)

    def publish(module_id, revision):
        return lambda: client.patch(
            f"/admin/content/modules/{module_id}",
            headers=admin_headers,
            json={"revision": revision, "is_active": True},
        )

    small_queries, response_small = query_counter(publish(small.id, small_revision))
    big_queries, response_big = query_counter(publish(big.id, big_revision))

    assert response_small.status_code == 200, response_small.text
    assert response_big.status_code == 200, response_big.text
    assert big_queries == small_queries, f"публикация выросла с {small_queries} до {big_queries} запросов"
    assert big_queries <= 40, big_queries
