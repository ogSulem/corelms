from __future__ import annotations

import json
import random
import re
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis
from app.core.rate_limit import rate_limit
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.attempt import QuizAttempt, QuizAttemptAnswer
from app.models.audit import LearningEvent, LearningEventType
from app.models.module import Submodule, Module
from app.models.quiz import Question, QuestionType, Quiz, QuizType
from app.models.user import User
from app.schemas.quiz import QuizStartResponse, QuizSubmitRequest, QuizSubmitResponse
from app.services.skills import record_activity_and_award_xp
from app.services.access import require_module_access, require_submodule_access, is_admin
from app.services.learning import LearningService, is_read_meta
from app.services.authoring import question_payload
from app.models.completion import LessonQuizVersion

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


def _session_key(user_id: str, quiz_id: str) -> str:
    return f"quiz_session:{user_id}:{quiz_id}"


def _map_option_letter(ch: str) -> str:
    c = (ch or "").strip().upper()
    # Support Russian option letters commonly used in prompts.
    # А Б В Г Д -> A B C D E
    if c == "А":
        return "A"
    if c == "Б":
        return "B"
    if c == "В":
        return "C"
    if c == "Г":
        return "D"
    if c == "Д":
        return "E"
    return c


def _normalize_single(answer: str) -> str:
    # Accept formats like: "A", "a", "A)", "answer: a", "(b)".
    # We extract the FIRST option letter A-D from the string.
    m = re.search(r"[A-Ea-eАБВГДабвгд]", (answer or ""))
    return (_map_option_letter(m.group(0)) if m else "")


def _normalize_multi(answer: str) -> str:
    # Accept formats like: "A,B,D", "ABD", "a b d".
    # We treat the answer as a set of option letters.
    letters = re.findall(r"[A-Ea-eАБВГДабвгд]", (answer or ""))
    norm = sorted({_map_option_letter(ch) for ch in letters if _map_option_letter(ch)})
    return ",".join(norm)


def _looks_like_multi(answer: str) -> bool:
    try:
        letters = {_map_option_letter(ch) for ch in re.findall(r"[A-Ea-eАБВГДабвгд]", (answer or ""))}
        return len(letters) >= 2
    except Exception:
        return False


def _is_correct(*, question: Question, answer: str) -> bool:
    expected = (question.correct_answer or "").strip()
    got = (answer or "").strip()

    if question.type.value == "case":
        # Free text is never graded as correct merely because it is non-empty.
        return bool(got and expected and expected.upper() != "ANY" and " ".join(expected.casefold().split()) == " ".join(got.casefold().split()))

    if question.type.value == "multi":
        return _normalize_multi(expected) == _normalize_multi(got)

    # single (and any other non-multi option-based type)
    # Accept any casing/separators by extracting option letters.
    # Be forgiving: if user/admin supplied multiple letters for a single-type question,
    # evaluate it as a multi-set comparison.
    if _looks_like_multi(expected) or _looks_like_multi(got):
        return _normalize_multi(expected) == _normalize_multi(got)

    exp = _normalize_single(expected)
    if exp:
        return exp == _normalize_single(got)

    return expected.lower() == got.lower()


def _is_final_quiz(quiz: Quiz) -> bool:
    return getattr(quiz.type, "value", str(quiz.type)) == QuizType.final.value


def _meta_action_is_read(meta: str | None) -> bool:
    if not meta:
        return False
    if str(meta).strip().lower() == "read":
        return True
    try:
        obj = json.loads(str(meta))
        if isinstance(obj, dict) and str(obj.get("action") or "").strip().lower() == "read":
            return True
    except Exception:
        return False
    return False


def _rebuild_final_quiz_from_lessons(*, db: Session, module: Module, final_quiz: Quiz) -> None:
    """Rebuild final quiz questions from lesson quiz questions.

    Product rule:
    - Each lesson contributes up to 2 random questions.
    - Final quiz is reassembled on each /start (fresh mix).
    """

    raise RuntimeError(
        "Final quiz questions must NOT be rebuilt or persisted in DB. "
        "Use _select_final_question_ids_from_lessons() and store the selected IDs in Redis quiz session on /start."
    )


def _select_final_question_ids_from_lessons(*, db: Session, module: Module) -> list[str]:
    subs = db.scalars(select(Submodule).where(Submodule.module_id == module.id,
        Submodule.is_archived.is_(False), Submodule.is_folder.is_(False)).order_by(Submodule.order)).all()

    rng = random.Random(f"final_open:{module.id}:{uuid.uuid4()}")

    # Build shuffled pools per submodule.
    pools: list[list[uuid.UUID]] = []
    for sub in subs:
        if not bool(getattr(sub, "requires_quiz", True)):
            continue
        if not sub.quiz_id:
            continue
        items = list(db.scalars(select(Question).where(Question.quiz_id == sub.quiz_id, ~func.coalesce(Question.concept_tag, "").like("needs_regen:%")).order_by(Question.id)))
        pool = [q.id for q in items if question_payload(q)["valid"]]
        if not pool:
            continue
        rng.shuffle(pool)
        pools.append(pool)

    selected: list[uuid.UUID] = []

    # Product rule (final test):
    # - Take up to 3 questions from EACH lesson submodule that has a quiz.
    # - If there are more than 10 such submodules, cap the final quiz to 30 questions total.
    #   (i.e. at most 10 submodules x 3 questions)
    max_submodules = 10
    per_submodule = 3
    max_total = max_submodules * per_submodule

    if not pools:
        return []

    # If there are too many lesson submodules, sample at most 10 of them.
    if len(pools) > max_submodules:
        rng.shuffle(pools)
        pools = pools[:max_submodules]

    # Round-robin selection: preserves per-submodule cap while filling up to max_total.
    for _ in range(per_submodule):
        for pool in pools:
            if len(selected) >= max_total:
                break
            if pool:
                selected.append(pool.pop(0))

    rng.shuffle(selected)
    return [str(qid) for qid in selected]


def _ensure_final_quiz_has_questions(*, db: Session, module: Module, final_quiz: Quiz) -> None:
    raise RuntimeError(
        "Final quiz questions must NOT be ensured/persisted in DB. "
        "Final quiz is assembled dynamically on /start from lesson quizzes."
    )


def _quiz_access(db: Session, user: User, quiz: Quiz, *, historical: bool = False) -> tuple[Module, Submodule | None]:
    sub = db.scalar(select(Submodule).where(Submodule.quiz_id == quiz.id))
    if sub is None and historical:
        sub = db.scalar(select(Submodule).join(LessonQuizVersion, LessonQuizVersion.submodule_id == Submodule.id)
                        .where(LessonQuizVersion.quiz_id == quiz.id))
    if sub is not None:
        module = require_submodule_access(db, user, sub, lock=True)
        db.refresh(sub)
        if sub.is_archived or sub.is_folder or not sub.requires_quiz or (not historical and sub.quiz_id != quiz.id):
            raise HTTPException(409, "Тест обновлён или недоступен. Вернитесь к уроку.")
        return module, sub
    module = db.scalar(select(Module).where(Module.final_quiz_id == quiz.id))
    if module is None:
        raise HTTPException(404, "Тест недоступен")
    return require_module_access(db, user, module.id, lock=True), None


@router.get("/{quiz_id}/context")
def quiz_context(quiz_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(404, "Тест недоступен")
    module, lesson = _quiz_access(db, user, quiz, historical=True)
    progress = LearningService(db).get_module_progress(user, module.id)
    status = next((s for s in progress["submodules"] if lesson and s["submodule_id"] == str(lesson.id)), None)
    ready = bool(status["read"]) if status else bool(progress["completed"] or all(s["completed"] for s in progress["submodules"]))
    attempts_used = db.scalar(select(func.count()).select_from(QuizAttempt).where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user.id)) or 0
    remaining = max(0, quiz.attempts_limit - attempts_used) if quiz.attempts_limit else None
    active_session = False
    try:
        raw = get_redis().get(_session_key(str(user.id), str(quiz.id)))
        session = json.loads(raw) if raw else {}
        active_session = bool(session.get("session_id") and session.get("question_ids"))
        if session.get("time_limit") and time.time() > int(session["started_at"]) + int(session["time_limit"]) + 30:
            active_session = False
    except Exception:
        pass
    blocked = ("Итоговый тест отключён администратором." if lesson is None and not module.final_quiz_enabled else
               "Лимит попыток исчерпан. Доступен разбор ответов; для новых попыток обратитесь к администратору." if remaining == 0 and not is_admin(user) else
               "Сначала завершите все уроки модуля." if lesson is None and not ready and not is_admin(user) else
               "Откройте материал урока и подтвердите его изучение." if not ready and not is_admin(user) else None)
    return {"module_id": str(module.id), "module_title": module.title,
            "submodule_id": str(lesson.id) if lesson else None, "title": lesson.title if lesson else "Итоговый тест",
            "current_quiz_id": str(lesson.quiz_id) if lesson else str(quiz.id),
            "is_final": lesson is None, "can_start": blocked is None or active_session, "can_resume": active_session, "start_blocked_reason": blocked if not active_session else None,
            "attempts_used": attempts_used, "attempts_remaining": remaining,
            "passed": status["passed"] if status else progress["final_passed"],
            "best_score": status["best_score"] if status else progress["final_best_score"],
            "pass_threshold": quiz.pass_threshold, "attempts_limit": quiz.attempts_limit}


@router.post("/{quiz_id}/start", response_model=QuizStartResponse)
def start_quiz(
    quiz_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: object = rate_limit(key_prefix="quiz_start", limit=30, window_seconds=60),
):
    try:
        quiz_uuid = uuid.UUID(quiz_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid quiz id") from e

    quiz = db.scalar(select(Quiz).where(Quiz.id == quiz_uuid))
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")

    is_final_quiz = _is_final_quiz(quiz)

    module, sub = _quiz_access(db, user, quiz, historical=True)
    if not is_admin(user):
        if sub is not None:
            metas = db.scalars(select(LearningEvent.meta).where(
                LearningEvent.user_id == user.id, LearningEvent.type == LearningEventType.submodule_opened,
                LearningEvent.ref_id == sub.id))
            if not any(is_read_meta(meta) for meta in metas):
                raise HTTPException(403, "confirm reading before starting quiz")
        else:
            progress = LearningService(db).get_module_progress(user, module.id)
            if not progress or (not progress["completed"] and not all(s["completed"] for s in progress["submodules"])):
                raise HTTPException(403, "Сначала завершите уроки модуля")

    attempts_used = db.scalar(
        select(func.count(QuizAttempt.id)).where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user.id)
    )

    # Idempotency: if a quiz session already exists, reuse it.
    # This prevents re-rolling questions, restarting timers, and duplicating quiz_started events.
    # Final and lesson quizzes both reuse an unfinished server-side session.
    r = None
    key = _session_key(str(user.id), str(quiz.id))
    existing_raw = None
    try:
        r = get_redis()
        existing_raw = r.get(key)
    except Exception:
        raise HTTPException(503, "Тестирование временно недоступно. Повторите попытку.")
    if existing_raw is not None:
        try:
            session = json.loads(existing_raw)
            existing_qids: list[str] = session.get("question_ids") or []
            if not existing_qids or len(set(existing_qids)) != len(existing_qids):
                raise ValueError("invalid session")
            session_id = str(session.get("session_id") or "")
            if not session_id:
                # A session started before this release can still be resumed safely.
                session_id = uuid.uuid4().hex
                session["session_id"] = session_id
                r.set(key, json.dumps(session), ex=max(1, r.ttl(key)))
            if db.scalar(select(QuizAttempt.id).where(QuizAttempt.session_id == session_id)):
                raise ValueError("session already submitted")
            session_limit = session.get("time_limit", quiz.time_limit)
            if session_limit and time.time() - int(session.get("started_at") or 0) > session_limit:
                raise ValueError("session timer expired")
            parsed: list[uuid.UUID] = []
            for qid in existing_qids:
                try:
                    parsed.append(uuid.UUID(qid))
                except ValueError:
                    continue

            if parsed:
                rows = list(db.scalars(select(Question).where(Question.id.in_(parsed))))
                qmap = {str(q.id): q for q in rows}
                ordered = [qmap.get(str(qid)) for qid in existing_qids]
                selected = [q for q in ordered if q is not None]

                if len(selected) != len(existing_qids):
                    raise ValueError("session questions changed")
                return QuizStartResponse(
                    quiz_id=str(quiz.id), session_id=session_id,
                    started_at=int(session["started_at"]), pass_threshold=session.get("pass_threshold", quiz.pass_threshold),
                    attempt_no=(attempts_used or 0) + 1, attempts_limit=session.get("attempts_limit", quiz.attempts_limit),
                    time_limit=session_limit,
                    questions=[{"id": str(q.id), "prompt": q.prompt, "type": q.type.value} for q in selected],
                )
        except Exception:
            # If session is corrupted, fall through and create a fresh one.
            pass

    if is_final_quiz and not module.final_quiz_enabled:
        raise HTTPException(409, "Итоговый тест отключён. Вернитесь к материалам модуля.")

    if sub is not None and sub.quiz_id != quiz.id:
        raise HTTPException(409, "Тест обновлён. Вернитесь к уроку, чтобы начать новую попытку.")

    if quiz.attempts_limit and int(attempts_used or 0) >= quiz.attempts_limit and not is_admin(user):
        raise HTTPException(409, "Лимит попыток исчерпан. Обратитесь к администратору.")

    selected_final_qids: list[str] | None = None
    if is_final_quiz:
        m = db.scalar(select(Module).where(Module.final_quiz_id == quiz.id))
        if m is None:
            raise HTTPException(status_code=404, detail="module not found")
        selected_final_qids = _select_final_question_ids_from_lessons(db=db, module=m)
        if not selected_final_qids:
            raise HTTPException(status_code=409, detail="final quiz has no source questions")

    questions: list[Question]
    if selected_final_qids is not None:
        parsed: list[uuid.UUID] = []
        for qid in selected_final_qids:
            try:
                parsed.append(uuid.UUID(qid))
            except ValueError:
                continue
        if not parsed:
            raise HTTPException(status_code=409, detail="final quiz has no source questions")
        rows = list(db.scalars(select(Question).where(Question.id.in_(parsed))))
        qmap = {str(q.id): q for q in rows}
        questions = [qmap.get(qid) for qid in selected_final_qids]
        questions = [q for q in questions if q is not None]
        if not questions:
            raise HTTPException(status_code=409, detail="final quiz has no source questions")
    else:
        questions = list(db.scalars(select(Question).where(Question.quiz_id == quiz.id, ~func.coalesce(Question.concept_tag, "").like("needs_regen:%"))))
        if not questions:
            raise HTTPException(status_code=400, detail="quiz has no questions")

    if any(not question_payload(q)["valid"] for q in questions):
        raise HTTPException(409, "Вопросы теста требуют проверки администратором: варианты или правильные ответы не настроены. Свободные ответы без ручной проверки не оцениваются автоматически.")

    grouped: dict[str, list[Question]] = {}
    singles: list[Question] = []
    for q in questions:
        if q.variant_group:
            grouped.setdefault(q.variant_group, []).append(q)
        else:
            singles.append(q)

    selected: list[Question] = []
    if is_final_quiz:
        # For final quizzes we must preserve the full question set (2 per lesson submodule).
        selected = list(questions)
        random.shuffle(selected)
    else:
        for _, group in grouped.items():
            selected.append(random.choice(group))
        selected.extend(singles)
        random.shuffle(selected)

    payload = {
        "session_id": uuid.uuid4().hex,
        "question_ids": [str(q.id) for q in selected],
        "started_at": int(time.time()),
        "pass_threshold": quiz.pass_threshold, "time_limit": quiz.time_limit, "attempts_limit": quiz.attempts_limit,
    }
    try:
        if r is not None:
            r.set(key, json.dumps(payload), ex=max(60, quiz.time_limit + 300) if quiz.time_limit else 60 * 60)
    except Exception as exc:
        raise HTTPException(503, "Не удалось сохранить сессию теста. Повторите попытку.") from exc

    # Count starting a quiz as activity for streak, but do not award XP.
    # Important: update streak BEFORE inserting the learning event to avoid autoflush affecting streak init.
    record_activity_and_award_xp(db, user_id=str(user.id), xp=0)

    # Enrich with module/submodule context when possible.
    sub_row = db.execute(
        select(Submodule.id, Submodule.module_id).where(Submodule.quiz_id == quiz.id).limit(1)
    ).first()
    sub_id = str(sub_row[0]) if sub_row and sub_row[0] else None
    mod_id = str(sub_row[1]) if sub_row and sub_row[1] else None

    meta = {
        "action": "start",
        "quiz_id": str(quiz.id),
        "attempt_no": int((attempts_used or 0) + 1),
        "module_id": mod_id,
        "submodule_id": sub_id,
    }
    db.add(
        LearningEvent(
            user_id=user.id,
            type=LearningEventType.quiz_started,
            ref_id=quiz.id,
            meta=json.dumps(meta, ensure_ascii=False),
        )
    )
    db.commit()

    return QuizStartResponse(
        quiz_id=str(quiz.id), session_id=payload["session_id"],
        started_at=payload["started_at"], pass_threshold=payload["pass_threshold"],
        attempt_no=(attempts_used or 0) + 1, attempts_limit=payload["attempts_limit"],
        time_limit=payload["time_limit"],
        questions=[{"id": str(q.id), "prompt": q.prompt, "type": q.type.value} for q in selected],
    )


def _submitted_result(db: Session, user: User, quiz: Quiz, session_id: str | None) -> QuizSubmitResponse | None:
    if not session_id:
        return None
    attempt = db.scalar(select(QuizAttempt).where(QuizAttempt.session_id == session_id,
                        QuizAttempt.user_id == user.id, QuizAttempt.quiz_id == quiz.id))
    if attempt is None or attempt.finished_at is None:
        return None
    total = db.scalar(select(func.count()).select_from(QuizAttemptAnswer).where(QuizAttemptAnswer.attempt_id == attempt.id)) or 0
    correct = db.scalar(select(func.count()).select_from(QuizAttemptAnswer).where(QuizAttemptAnswer.attempt_id == attempt.id, QuizAttemptAnswer.is_correct.is_(True))) or 0
    return QuizSubmitResponse(quiz_id=str(quiz.id), score=int(attempt.score or 0), passed=attempt.passed,
                              correct=correct, total=total, xp_awarded=attempt.xp_awarded, replayed=True)


@router.post("/{quiz_id}/submit", response_model=QuizSubmitResponse)
def submit_quiz(
    quiz_id: str,
    body: QuizSubmitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: object = rate_limit(key_prefix="quiz_submit", limit=20, window_seconds=60),
):
    try:
        quiz_uuid = uuid.UUID(quiz_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid quiz id") from e

    quiz = db.scalar(select(Quiz).where(Quiz.id == quiz_uuid))
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")

    module, sub = _quiz_access(db, user, quiz, historical=True)
    is_final_quiz = _is_final_quiz(quiz)
    previous_result = _submitted_result(db, user, quiz, body.session_id)
    if previous_result is not None:
        return previous_result

    r = None
    key = _session_key(str(user.id), str(quiz.id))
    raw = None
    try:
        r = get_redis()
        raw = r.get(key)
    except Exception as exc:
        raise HTTPException(503, "Тестирование временно недоступно. Ответы не потеряны — повторите отправку.") from exc
    question_ids: list[str] = []
    started_at: int | None = None
    time_spent: int | None = None

    if raw is None:
        # Client-provided question subsets must never define the denominator.
        raise HTTPException(409, "quiz session not found or expired")
    else:
        try:
            session = json.loads(raw)
            session_id = str(session.get("session_id") or "")
            if not session_id:
                # Stable token for pre-release sessions, including retries after a Redis failure.
                session_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{user.id}:{quiz.id}:{session.get('started_at')}").hex
            if body.session_id and body.session_id != session_id:
                raise HTTPException(409, "В другой вкладке начата новая попытка. Вернитесь к уроку.")
            previous_result = _submitted_result(db, user, quiz, session_id)
            if previous_result is not None:
                return previous_result
            question_ids = session.get("question_ids") or []
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(409, "Сессия теста повреждена. Начните новую попытку.") from exc

        started_at = int(session.get("started_at") or 0)
        time_spent = max(0, int(time.time()) - started_at)
        session_limit = session.get("time_limit", quiz.time_limit)
        if session_limit and time_spent > session_limit:
            raise HTTPException(status_code=409, detail="time limit exceeded")

    if not question_ids or len(set(question_ids)) != len(question_ids):
        raise HTTPException(409, "invalid quiz session")
    if len({a.question_id for a in body.answers}) != len(body.answers) or any(a.question_id not in question_ids for a in body.answers):
        raise HTTPException(422, "Ответы должны относиться к вопросам текущей попытки и не повторяться")
    answers_by_qid = {a.question_id: a.answer for a in body.answers}

    parsed_question_ids: list[uuid.UUID] = []
    for qid in question_ids:
        try:
            parsed_question_ids.append(uuid.UUID(qid))
        except (ValueError, TypeError):
            raise HTTPException(409, "invalid quiz session")

    if is_final_quiz:
        m = db.scalar(select(Module).where(Module.final_quiz_id == quiz.id))
        if m is None:
            raise HTTPException(status_code=404, detail="module not found")
        # Keep consistent with /start: final quiz is built from LESSON submodules only (exclude last/final submodule).
        active_lessons = list(db.scalars(select(Submodule).where(
            Submodule.module_id == m.id)))
        allowed_quiz_ids = [s.quiz_id for s in active_lessons]
        allowed_quiz_ids.extend(db.scalars(select(LessonQuizVersion.quiz_id).where(
            LessonQuizVersion.submodule_id.in_([s.id for s in active_lessons]))))
        if not allowed_quiz_ids:
            raise HTTPException(status_code=409, detail="final quiz has no source quizzes")
        questions = list(db.scalars(select(Question).where(Question.id.in_(parsed_question_ids), Question.quiz_id.in_(allowed_quiz_ids))))
    else:
        questions = list(
            db.scalars(
                select(Question).where(
                    Question.id.in_(parsed_question_ids),
                    Question.quiz_id == quiz.id,
                )
            )
        )
    qmap = {str(q.id): q for q in questions}

    if len(qmap) != len({str(x) for x in parsed_question_ids}):
        raise HTTPException(status_code=409, detail="invalid questions for this quiz")

    if any(not question_payload(question)["valid"] for question in questions):
        raise HTTPException(409, "В старой попытке есть вопросы, которые нельзя проверить автоматически. Результат не записан и попытка не потрачена. Обратитесь к администратору для проверки теста.")

    correct = 0
    total = len(question_ids)

    attempt_no = (
        db.scalar(select(func.count(QuizAttempt.id)).where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user.id)) or 0
    ) + 1

    attempt_started_at = datetime.utcfromtimestamp(started_at) if started_at else datetime.utcnow()
    attempt = QuizAttempt(quiz_id=quiz.id, user_id=user.id, attempt_no=attempt_no, started_at=attempt_started_at, session_id=session_id)
    db.add(attempt)
    db.flush()

    for qid in question_ids:
        q = qmap.get(qid)
        if q is None:
            continue
        ans = answers_by_qid.get(qid, "")
        ok = _is_correct(question=q, answer=ans)
        if ok:
            correct += 1
        db.add(QuizAttemptAnswer(attempt_id=attempt.id, question_id=q.id, answer=ans, is_correct=ok))

    score = int(round((correct / total) * 100)) if total > 0 else 0
    passed = score >= int(session.get("pass_threshold", quiz.pass_threshold))

    attempt.finished_at = datetime.utcnow()
    attempt.score = score
    attempt.passed = passed
    attempt.time_spent_seconds = time_spent

    # Award mastery once per stable lesson, not again for each regenerated quiz.
    family = [quiz.id]
    if sub is not None:
        family = list(db.scalars(select(LessonQuizVersion.quiz_id).where(LessonQuizVersion.submodule_id == sub.id)))
        family = list(set(family + [quiz.id, sub.quiz_id]))
    with db.no_autoflush:
        previous = list(db.scalars(select(QuizAttempt).where(QuizAttempt.quiz_id.in_(family),
                             QuizAttempt.user_id == user.id, QuizAttempt.id != attempt.id)))
    xp_award = 25 if passed and not any(a.passed for a in previous) else 5 if not passed and not previous else 0
    attempt.xp_awarded = xp_award

    # Important: update streak/xp BEFORE inserting the learning event, so streak init works reliably.
    record_activity_and_award_xp(db, user_id=str(user.id), xp=xp_award)

    db.add(
        LearningEvent(
            user_id=user.id,
            type=LearningEventType.quiz_completed,
            ref_id=quiz.id,
            meta=json.dumps(
                {
                    "action": "finish",
                    "quiz_id": str(quiz.id),
                    "attempt_no": int(attempt_no),
                    "score": int(score),
                    "passed": bool(passed),
                    "correct": int(correct),
                    "total": int(total),
                    "time_spent_seconds": int(time_spent) if time_spent is not None else None,
                },
                ensure_ascii=False,
            ),
        )
    )

    LearningService(db).remember_completions(module, user)
    db.commit()

    try:
        if r is not None:
            r.delete(key)
    except Exception:
        pass

    return QuizSubmitResponse(
        quiz_id=str(quiz.id),
        score=score,
        passed=passed,
        correct=correct,
        total=total,
        xp_awarded=int(xp_award),
    )


@router.get("/{quiz_id}/attempts/latest")
def latest_attempt_review(quiz_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    quiz = db.get(Quiz, quiz_id)
    if not quiz:
        raise HTTPException(404, "Тест недоступен")
    _quiz_access(db, user, quiz, historical=True)
    attempt = db.scalar(select(QuizAttempt).where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user.id,
        QuizAttempt.finished_at.is_not(None)).order_by(QuizAttempt.finished_at.desc(), QuizAttempt.id).limit(1))
    if not attempt:
        return {"attempt": None, "can_review": False, "questions": []}
    used = db.scalar(select(func.count()).select_from(QuizAttempt).where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user.id)) or 0
    can_review = attempt.passed or bool(quiz.attempts_limit and used >= quiz.attempts_limit) or is_admin(user)
    rows = list(db.execute(select(QuizAttemptAnswer, Question).join(Question, Question.id == QuizAttemptAnswer.question_id)
        .where(QuizAttemptAnswer.attempt_id == attempt.id).order_by(Question.position, Question.id)))
    return {"attempt": {"id": str(attempt.id), "score": attempt.score, "passed": attempt.passed,
                        "attempt_no": attempt.attempt_no, "finished_at": attempt.finished_at.isoformat()},
            "can_review": can_review, "attempts_remaining": max(0, quiz.attempts_limit - used) if quiz.attempts_limit else None,
            "questions": [{"id": str(q.id), "prompt": q.prompt, "type": q.type.value, "answer": a.answer,
                **({"is_correct": a.is_correct, "correct_answer": q.correct_answer, "explanation": q.explanation} if can_review else {})}
                for a, q in rows]}
