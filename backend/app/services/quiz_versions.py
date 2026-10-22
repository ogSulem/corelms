"""Copy-on-write question editing: live sessions and historical answers are immutable."""
from __future__ import annotations

import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.attempt import QuizAttempt, QuizAttemptAnswer
from app.models.completion import LessonQuizVersion
from app.models.module import Module, Submodule
from app.models.quiz import Question, Quiz
from app.services.content import lock_module, preserve_progress
from app.services.learning import remember_quiz_version


def version_quiz_for_edit(db: Session, quiz_id: uuid.UUID, *, exclude: uuid.UUID | None = None) -> tuple[Quiz, dict[uuid.UUID, Question]]:
    source = db.get(Quiz, quiz_id)
    if source is None:
        raise HTTPException(404, "Тест не найден")
    lesson = db.scalar(select(Submodule).where(Submodule.quiz_id == quiz_id))
    questions = list(db.scalars(select(Question).where(Question.quiz_id == quiz_id).order_by(Question.id)))
    if lesson is None:
        if db.get(LessonQuizVersion, quiz_id) is not None:
            raise HTTPException(409, "Тест уже обновлён. Обновите список вопросов перед редактированием.")
        if db.scalar(select(Module.id).where(Module.final_quiz_id == quiz_id)):
            raise HTTPException(409, "Итоговый тест собирается из уроков. Редактируйте вопросы соответствующего урока.")
        has_history = db.scalar(select(QuizAttempt.id).where(QuizAttempt.quiz_id == quiz_id).limit(1))
        has_answers = db.scalar(select(QuizAttemptAnswer.id).where(QuizAttemptAnswer.question_id.in_([q.id for q in questions])).limit(1))
        if has_history or has_answers:
            raise HTTPException(409, "Архивный тест доступен только для чтения")
        # Legacy API may prepare an unattached quiz before creating a lesson.
        if exclude:
            for q in questions:
                if q.id == exclude:
                    db.delete(q)
        return source, {q.id: q for q in questions if q.id != exclude}

    module = lock_module(db, lesson.module_id)
    db.refresh(lesson)
    if lesson.quiz_id != quiz_id or module.is_archived or lesson.is_archived or lesson.is_folder:
        raise HTTPException(409, "Материал изменён или находится в архиве. Обновите редактор.")
    if exclude and lesson.requires_quiz and len(questions) <= 1:
        raise HTTPException(409, "Нельзя оставить обязательный тест без вопросов. Сначала выключите тест у урока.")
    preserve_progress(db, module)
    remember_quiz_version(db, lesson)
    target = Quiz(type=source.type, pass_threshold=source.pass_threshold,
                  time_limit=source.time_limit, attempts_limit=source.attempts_limit)
    db.add(target)
    db.flush()
    mapping = {}
    for old in questions:
        if old.id == exclude:
            continue
        new = Question(quiz_id=target.id, type=old.type, difficulty=old.difficulty,
                       position=old.position, prompt=old.prompt, correct_answer=old.correct_answer,
                       explanation=old.explanation, concept_tag=old.concept_tag, variant_group=old.variant_group)
        db.add(new)
        mapping[old.id] = new
    lesson.quiz_id = target.id
    module.content_revision += 1
    db.flush()
    remember_quiz_version(db, lesson)
    return target, mapping


def question_id_map(mapping: dict[uuid.UUID, Question]) -> dict[str, str]:
    return {str(old_id): str(question.id) for old_id, question in mapping.items()}
