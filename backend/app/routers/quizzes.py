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
        if expected.upper() == "ANY":
            return bool(got)
        return bool(got)

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
    subs = db.scalars(select(Submodule).where(Submodule.module_id == module.id).order_by(Submodule.order)).all()

    # Product rule: final quiz should take up to 2 questions from EACH lesson submodule.
    # We explicitly exclude the final submodule (the last one by order) because it represents the final test itself.
    last_sub_id = None
    try:
        last_sub_id = db.scalar(
            select(Submodule.id)
            .where(Submodule.module_id == module.id)
            .order_by(Submodule.order.desc())
            .limit(1)
        )
    except Exception:
        last_sub_id = None

    rng = random.Random(f"final_open:{module.id}:{uuid.uuid4()}")

    # Build shuffled pools per submodule.
    pools: list[list[uuid.UUID]] = []
    for sub in subs:
        if last_sub_id is not None and sub.id == last_sub_id:
            continue
        if not sub.quiz_id:
            continue
        items = list(db.scalars(select(Question.id).where(Question.quiz_id == sub.quiz_id).order_by(Question.id)))
        pool = [qid for qid in (items or []) if qid is not None]
        if not pool:
            continue
        rng.shuffle(pool)
        pools.append(pool)

    selected: list[uuid.UUID] = []

    # Phase 1: up to 2 questions per submodule.
    for pool in pools:
        if pool:
            selected.append(pool.pop(0))
        if pool:
            selected.append(pool.pop(0))

    # Phase 2: ensure at least 10 questions when possible.
    # Add 1 per submodule in round-robin passes until reaching 10 or pools are exhausted.
    target_min = 10
    while len(selected) < target_min:
        progressed = False
        for pool in pools:
            if len(selected) >= target_min:
                break
            if pool:
                selected.append(pool.pop(0))
                progressed = True
        if not progressed:
            break

    rng.shuffle(selected)
    return [str(qid) for qid in selected]


def _ensure_final_quiz_has_questions(*, db: Session, module: Module, final_quiz: Quiz) -> None:
    raise RuntimeError(
        "Final quiz questions must NOT be ensured/persisted in DB. "
        "Final quiz is assembled dynamically on /start from lesson quizzes."
    )


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

    # Product rule: quiz is available only after the learner explicitly confirms reading the submodule.
    sub = db.scalar(select(Submodule).where(Submodule.quiz_id == quiz.id))
    if sub is not None:
        # Check if this is the final submodule of the module
        is_final = db.scalar(
            select(Submodule.id)
            .where(Submodule.module_id == sub.module_id)
            .order_by(Submodule.order.desc())
            .limit(1)
        ) == sub.id

        # ONLY require read confirmation for non-final submodules (lessons)
        # Because final tests in Taiga LMS don't have theory blocks.
        if not is_final:
            metas = db.scalars(
                select(LearningEvent.meta)
                .where(
                    LearningEvent.user_id == user.id,
                    LearningEvent.type == LearningEventType.submodule_opened,
                    LearningEvent.ref_id == sub.id,
                    LearningEvent.meta.is_not(None),
                )
                .order_by(LearningEvent.created_at.desc())
                .limit(20)
            ).all()
            if not any(_meta_action_is_read(m) for m in (metas or [])):
                raise HTTPException(status_code=403, detail="confirm reading before starting quiz")

    attempts_used = db.scalar(
        select(func.count(QuizAttempt.id)).where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user.id)
    )

    # Idempotency: if a quiz session already exists, reuse it.
    # This prevents re-rolling questions, restarting timers, and duplicating quiz_started events.
    # IMPORTANT: final quizzes must be rebuilt on each open (fresh mix), so we bypass reuse for final.
    r = None
    key = _session_key(str(user.id), str(quiz.id))
    existing_raw = None
    try:
        r = get_redis()
        existing_raw = None if is_final_quiz else r.get(key)
    except Exception:
        r = None
        existing_raw = None
    if existing_raw is not None:
        try:
            session = json.loads(existing_raw)
            existing_qids: list[str] = session.get("question_ids") or []
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

                return QuizStartResponse(
                    quiz_id=str(quiz.id),
                    attempt_no=(attempts_used or 0) + 1,
                    time_limit=quiz.time_limit,
                    questions=[{"id": str(q.id), "prompt": q.prompt, "type": q.type.value} for q in selected],
                )
        except Exception:
            # If session is corrupted, fall through and create a fresh one.
            pass

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
        questions = list(db.scalars(select(Question).where(Question.quiz_id == quiz.id)))
        if not questions:
            raise HTTPException(status_code=400, detail="quiz has no questions")

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
        "question_ids": [str(q.id) for q in selected],
        "started_at": int(time.time()),
    }
    try:
        if r is not None:
            r.set(key, json.dumps(payload), ex=quiz.time_limit if quiz.time_limit else 60 * 60)
    except Exception:
        # Redis is best-effort. If it's unavailable, we still allow the quiz to start.
        pass

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
        quiz_id=str(quiz.id),
        attempt_no=(attempts_used or 0) + 1,
        time_limit=quiz.time_limit,
        questions=[{"id": str(q.id), "prompt": q.prompt, "type": q.type.value} for q in selected],
    )


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

    is_final_quiz = _is_final_quiz(quiz)

    r = None
    key = _session_key(str(user.id), str(quiz.id))
    raw = None
    try:
        r = get_redis()
        raw = r.get(key)
    except Exception:
        r = None
        raw = None
    question_ids: list[str] = []
    started_at: int | None = None
    time_spent: int | None = None

    if raw is None:
        # Fallback mode: Redis session may be lost on restart.
        # We accept submission using question ids from the request body,
        # but only if they all belong to this quiz.
        question_ids = [a.question_id for a in (body.answers or []) if a.question_id]
        if not question_ids:
            raise HTTPException(status_code=409, detail="quiz session not found or expired")
    else:
        session = json.loads(raw)
        question_ids = session.get("question_ids") or []

        started_at = int(session.get("started_at") or 0)
        time_spent = max(0, int(time.time()) - started_at)
        if quiz.time_limit and time_spent > quiz.time_limit:
            raise HTTPException(status_code=409, detail="time limit exceeded")

    answers_by_qid = {a.question_id: a.answer for a in body.answers}

    parsed_question_ids: list[uuid.UUID] = []
    for qid in question_ids:
        try:
            parsed_question_ids.append(uuid.UUID(qid))
        except ValueError:
            continue

    if is_final_quiz:
        m = db.scalar(select(Module).where(Module.final_quiz_id == quiz.id))
        if m is None:
            raise HTTPException(status_code=404, detail="module not found")
        # Keep consistent with /start: final quiz is built from LESSON submodules only (exclude last/final submodule).
        last_sub_id = None
        try:
            last_sub_id = db.scalar(
                select(Submodule.id)
                .where(Submodule.module_id == m.id)
                .order_by(Submodule.order.desc())
                .limit(1)
            )
        except Exception:
            last_sub_id = None

        rows = db.execute(
            select(Submodule.id, Submodule.quiz_id)
            .where(Submodule.module_id == m.id)
            .where(Submodule.quiz_id.is_not(None))
        ).all()
        allowed_quiz_ids = []
        for sid, qid in rows:
            if last_sub_id is not None and sid == last_sub_id:
                continue
            if qid is not None:
                allowed_quiz_ids.append(qid)
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

    correct = 0
    total = len(question_ids)

    attempt_no = (
        db.scalar(select(func.count(QuizAttempt.id)).where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user.id)) or 0
    ) + 1

    attempt_started_at = datetime.utcfromtimestamp(started_at) if started_at else datetime.utcnow()
    attempt = QuizAttempt(quiz_id=quiz.id, user_id=user.id, attempt_no=attempt_no, started_at=attempt_started_at)
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
    passed = score >= quiz.pass_threshold

    attempt.finished_at = datetime.utcnow()
    attempt.score = score
    attempt.passed = passed
    attempt.time_spent_seconds = time_spent

    # XP rules (idempotent):
    # - First ever PASS for this quiz => +25
    # - First attempt fail => +5 (activity)
    # Note: must query prev_passes WITHOUT including current attempt (avoid autoflush).
    xp_award = 0
    if passed:
        with db.no_autoflush:
            prev_passes = db.scalar(
                select(func.count(QuizAttempt.id)).where(
                    QuizAttempt.quiz_id == quiz.id,
                    QuizAttempt.user_id == user.id,
                    QuizAttempt.passed == True,  # noqa: E712
                )
            )
        if not prev_passes or prev_passes <= 0:
            xp_award = 25
    else:
        if attempt_no == 1:
            xp_award = 5

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

    skill_changes: list[dict] = []

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
