"""Отчёт «Результаты»: быстрый путь обязан совпадать с полным расчётом.

В отчёте по всему каталогу большинство пар «человек × модуль» — пустые. Быстрый
путь не перебирает уроки такого модуля, а сразу отдаёт заранее известный ответ.
Тест доказывает, что ответ побайтово совпадает с полным расчётом на данных, где
есть и прочитанный урок, и пройденный тест, и завершение модуля.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.audit import LearningEvent, LearningEventType
from app.models.completion import ModuleCompletion
from app.models.attempt import QuizAttempt
from app.services.learning import LearningService


def _matrix(db, users, modules):
    return LearningService(db).get_progress_matrix(users, modules)


def test_fast_path_matches_the_full_calculation(db, make_module, make_user, monkeypatch):
    from app.services import learning as learning_module

    read_module, read_lesson, _read_quiz = make_module(title="Прочитанный модуль", final=True)
    done_module, done_lesson, _ = make_module(title="Пройденный модуль", required=True)
    untouched_module, _lesson, _quiz = make_module(title="Нетронутый модуль")

    reader, _ = make_user()
    finisher, _ = make_user()
    idle, _ = make_user()

    db.add(LearningEvent(user_id=reader.id, type=LearningEventType.submodule_opened,
                         ref_id=read_lesson.id, meta="read"))
    db.add(QuizAttempt(user_id=finisher.id, quiz_id=done_lesson.quiz_id, attempt_no=1,
                       passed=True, score=100, finished_at=datetime.now(timezone.utc)))
    db.add(ModuleCompletion(user_id=finisher.id, module_id=done_module.id, content_revision=1))
    db.commit()

    users = [reader, finisher, idle]
    modules = [read_module, done_module, untouched_module]

    monkeypatch.setattr(learning_module, "_COMPACT_FAST_PATH", False)
    full = _matrix(db, users, modules)
    monkeypatch.setattr(learning_module, "_COMPACT_FAST_PATH", True)
    fast = _matrix(db, users, modules)

    assert fast == full, "быстрый путь не должен менять ответ отчёта"
    # Пустая ячейка действительно пустая, но модуль с уроками остаётся доступным.
    idle_cell = fast[(idle.id, untouched_module.id)]
    assert idle_cell["has_materials"] is True
    assert idle_cell["total"] == 1 and idle_cell["passed"] == 0
    assert idle_cell["completed"] is False and idle_cell["has_updates"] is False
    assert idle_cell["submodules"] == []
    # Данные читателя и завершившего не потерялись.
    assert fast[(reader.id, read_module.id)]["read_count"] == 1
    assert fast[(finisher.id, done_module.id)]["completed"] is True


def test_fast_path_keeps_final_quiz_in_the_total(db, make_module, make_user, monkeypatch):
    from app.services import learning as learning_module

    module, _lesson, _quiz = make_module(title="Модуль с финалом", required=True, final=True)
    learner, _ = make_user()
    monkeypatch.setattr(learning_module, "_COMPACT_FAST_PATH", True)
    cell = _matrix(db, [learner], [module])[(learner.id, module.id)]
    assert cell["total"] == 2  # урок + финальный тест
    assert cell["final_quiz_id"] is not None and cell["final_passed"] is False
    assert cell["completed"] is False


def test_fast_path_reports_module_without_lessons_as_empty(db, make_module, make_user, monkeypatch):
    from app.services import learning as learning_module

    module, lesson, _ = make_module(title="Модуль без уроков")
    lesson.is_archived = True
    db.commit()
    learner, _ = make_user()
    monkeypatch.setattr(learning_module, "_COMPACT_FAST_PATH", True)
    cell = _matrix(db, [learner], [module])[(learner.id, module.id)]
    assert cell["total"] == 0 and cell["has_materials"] is False
    assert cell["completed"] is False
