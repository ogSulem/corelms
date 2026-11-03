import uuid

from sqlalchemy import func, select

from app.models.attempt import QuizAttempt, QuizAttemptAnswer
from app.models.completion import LessonQuizVersion
from app.models.quiz import Question, Quiz, QuizType
from app.models.module import Submodule
from app.services.quiz_versions import cleanup_superseded_quiz_versions


def _quiz_with_questions(db, count=2):
    quiz = Quiz(type=QuizType.submodule)
    db.add(quiz)
    db.flush()
    questions = []
    for index in range(count):
        question = Question(quiz_id=quiz.id, type="single", position=index + 1,
                            prompt=f"Вопрос {index + 1}", correct_answer="A")
        db.add(question)
        questions.append(question)
    db.flush()
    return quiz.id, questions


def _version(db, lesson, questions):
    """Новая версия теста — ровно то, что делает сохранение теста урока."""
    quiz_id, _ = _quiz_with_questions(db, 0)
    for old in questions:
        db.add(Question(quiz_id=quiz_id, type=old.type, position=old.position, prompt=old.prompt,
                        correct_answer=old.correct_answer))
    lesson.quiz_id = quiz_id
    db.add(LessonQuizVersion(quiz_id=quiz_id, submodule_id=lesson.id))
    db.flush()
    return quiz_id


def test_cleanup_removes_unattempted_versions_and_keeps_current(client, db, make_module, make_user):
    module, lesson, _ = make_module()
    first, questions = _quiz_with_questions(db)
    lesson.quiz_id = first
    db.add(LessonQuizVersion(quiz_id=first, submodule_id=lesson.id))
    db.commit()

    versions = [first]
    for _ in range(4):
        versions.append(_version(db, lesson, questions))
        questions = list(db.scalars(select(Question).where(Question.quiz_id == lesson.quiz_id)))
    db.commit()
    lesson_id, current_id = lesson.id, lesson.quiz_id
    assert len(versions) == 5

    removed = cleanup_superseded_quiz_versions(db, lesson_id)
    db.commit()
    db.expire_all()

    assert removed == 4, "все непригодившиеся копии должны уйти"
    assert db.get(Quiz, current_id) is not None, "текущий тест урока остаётся"
    # Вопросы остаются только у текущей версии: остальное — дубликаты.
    assert db.scalar(select(func.count()).select_from(Question).where(Question.quiz_id.in_(versions))) == 2
    # Строки версий сохраняются: по ним старый тест объясняет, что его заменили.
    assert set(db.scalars(select(Quiz.id).where(Quiz.id.in_(versions)))) == set(versions)
    assert db.scalar(select(func.count()).select_from(LessonQuizVersion).where(
        LessonQuizVersion.submodule_id == lesson_id)) == 5


def test_cleanup_keeps_versions_with_attempts_and_answers(client, db, make_module, make_user):
    module, lesson, _ = make_module()
    learner, _headers = make_user()
    first, questions = _quiz_with_questions(db)
    question_id = questions[0].id
    lesson.quiz_id = first
    db.add(LessonQuizVersion(quiz_id=first, submodule_id=lesson.id))
    attempt = QuizAttempt(user_id=learner.id, quiz_id=first, attempt_no=1)
    db.add(attempt)
    db.flush()
    db.add(QuizAttemptAnswer(attempt_id=attempt.id, question_id=question_id, answer="A", is_correct=True))
    db.commit()

    current = _version(db, lesson, questions)
    dead = _version(db, lesson, list(db.scalars(select(Question).where(Question.quiz_id == current))))
    _version(db, lesson, list(db.scalars(select(Question).where(Question.quiz_id == dead))))
    db.commit()
    lesson_id = lesson.id

    removed = cleanup_superseded_quiz_versions(db, lesson_id)
    db.commit()
    db.expire_all()

    assert removed == 2, "без попыток были только две промежуточные версии"
    assert db.get(Question, question_id) is not None, "вопросы пройденной версии неприкосновенны"
    assert db.scalar(select(func.count()).select_from(Question).where(
        Question.quiz_id.in_([current, dead]))) == 0
    assert db.scalar(select(func.count()).select_from(QuizAttemptAnswer)) == 1


def test_cleanup_never_touches_current_or_foreign_lesson(client, db, make_module):
    module, lesson, _ = make_module()
    foreign_quiz, foreign_questions = _quiz_with_questions(db)
    other = Submodule(module_id=module.id, title="Другой урок", order=99, content="текст",
                      quiz_id=foreign_quiz)
    db.add(other)
    db.flush()

    own, _questions = _quiz_with_questions(db)
    lesson.quiz_id = own
    db.add(LessonQuizVersion(quiz_id=own, submodule_id=lesson.id))
    db.add(LessonQuizVersion(quiz_id=foreign_quiz, submodule_id=other.id))
    db.commit()
    lesson_id = lesson.id
    foreign_question_id = foreign_questions[0].id

    assert cleanup_superseded_quiz_versions(db, lesson_id) == 0
    db.commit()
    db.expire_all()
    assert db.get(Quiz, own) is not None
    assert db.get(Quiz, foreign_quiz) is not None
    assert db.get(Question, foreign_question_id) is not None
    assert cleanup_superseded_quiz_versions(db, uuid.uuid4()) == 0


def test_cleanup_keeps_version_with_unfinished_learner_session(client, db, make_module, make_user, redis_memory):
    """Начатый, но не отправленный тест живёт только в Redis: его версия неприкосновенна."""
    module, lesson, _ = make_module()
    learner, _headers = make_user()
    first, questions = _quiz_with_questions(db)
    lesson.quiz_id = first
    db.add(LessonQuizVersion(quiz_id=first, submodule_id=lesson.id))
    db.commit()

    current = _version(db, lesson, questions)
    db.commit()
    lesson_id, question_id = lesson.id, questions[0].id
    redis_memory.set(f"quiz_session:{learner.id}:{first}", "{}")

    assert cleanup_superseded_quiz_versions(db, lesson_id) == 0
    db.commit()
    db.expire_all()
    assert db.get(Question, question_id) is not None, "ученик должен суметь продолжить тест"
    assert db.get(Quiz, first) is not None
    assert db.get(Quiz, current) is not None
