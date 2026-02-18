from __future__ import annotations

from datetime import datetime
import random
import uuid
import logging

from rq import get_current_job
from sqlalchemy import delete, select
from sqlalchemy import func

from app.db.session import SessionLocal
from app.models.module import Module, Submodule
from app.models.quiz import Question, QuestionType, Quiz, QuizType
from app.services.llm_handler import choose_llm_provider_order_fast, generate_quiz_questions_ai
from app.services.quiz_generation import generate_quiz_questions_heuristic


log = logging.getLogger(__name__)


def _set_job_stage(*, stage: str, detail: str | None = None) -> None:
    try:
        job = get_current_job()
    except Exception:
        job = None
    if job is None:
        return

    try:
        now = datetime.utcnow()
        meta = dict(job.meta or {})

        prev_stage = str(meta.get("stage") or "")
        prev_started_at = str(meta.get("stage_started_at") or "")
        if not meta.get("job_started_at"):
            meta["job_started_at"] = now.isoformat()

        if prev_stage and prev_started_at and prev_stage != str(stage):
            try:
                prev_dt = datetime.fromisoformat(prev_started_at)
                dur = max(0.0, (now - prev_dt).total_seconds())
                durs = dict(meta.get("stage_durations_s") or {})
                durs[prev_stage] = float(durs.get(prev_stage) or 0.0) + float(dur)
                meta["stage_durations_s"] = durs
            except Exception:
                pass

        meta["stage"] = str(stage)
        meta["stage_at"] = now.isoformat()
        meta["stage_started_at"] = now.isoformat()
        if detail is not None:
            meta["detail"] = str(detail)
        job.meta = meta
        job.save_meta()
    except Exception:
        return


def _job_heartbeat(*, detail: str | None = None) -> None:
    try:
        job = get_current_job()
    except Exception:
        job = None
    if job is None:
        return
    try:
        now = datetime.utcnow().isoformat()
        meta = dict(job.meta or {})
        meta["stage_at"] = now
        if detail is not None:
            meta["detail"] = str(detail)
        job.meta = meta
        job.save_meta()
    except Exception:
        return


def _is_cancel_requested() -> bool:
    try:
        job = get_current_job()
    except Exception:
        job = None
    if job is None:
        return False
    try:
        meta = dict(job.meta or {})
        return bool(meta.get("cancel_requested"))
    except Exception:
        return False


class RegenCanceledError(RuntimeError):
    pass


def _cancel_checkpoint(*, stage: str) -> None:
    if not _is_cancel_requested():
        return
    _set_job_stage(stage="canceled", detail=f"{stage}: cancel")
    raise RegenCanceledError("regen canceled")


def _set_job_error(*, error: Exception, error_code: str | None = None, error_hint: str | None = None) -> None:
    try:
        job = get_current_job()
    except Exception:
        job = None
    if job is None:
        return

    try:
        meta = dict(job.meta or {})
        msg = str(error or "")
        meta["error_code"] = str(error_code or "").strip() or "REGEN_FAILED"
        meta["error_class"] = type(error).__name__
        meta["error_message"] = msg
        meta["error_hint"] = (
            str(error_hint or "").strip() or "Проверьте доступность AI провайдера и лог ошибок worker."
        )
        job.meta = meta
        job.save_meta()
    except Exception:
        return


def regenerate_module_quizzes_job(*, module_id: str, target_questions: int = 5) -> dict:
    _set_job_stage(stage="start", detail=str(module_id))

    db = SessionLocal()
    try:
        mid_raw = str(module_id).strip()
        try:
            mid = uuid.UUID(mid_raw)
        except Exception as e:
            _set_job_stage(stage="failed", detail="invalid module_id")
            _set_job_error(
                error=e,
                error_code="INVALID_MODULE_ID",
                error_hint="Неверный module_id (UUID). Проверьте, что задача регена создана для существующего модуля.",
            )
            raise ValueError("invalid module_id") from e

        m = db.scalar(select(Module).where(Module.id == mid))
        if m is None:
            _set_job_stage(stage="failed", detail="module not found")
            _set_job_error(
                error=ValueError("module not found"),
                error_code="MODULE_NOT_FOUND",
                error_hint=(
                    "Модуль не найден в базе. Возможные причины: модуль удалён, импорт не завершился, "
                    "или реген запущен для старого/неактуального module_id (например после повторного импорта/дубликата)."
                ),
            )
            raise ValueError("module not found")

        subs = db.scalars(select(Submodule).where(Submodule.module_id == m.id).order_by(Submodule.order)).all()

        _set_job_stage(stage="load", detail=f"lessons: {len(subs)}")
        _cancel_checkpoint(stage="load")

        report: dict[str, object] = {
            "ok": True,
            "module_id": str(module_id),
            "module_title": str(m.title),
            "lessons": int(len(subs)),
            "questions_total": 0,
            "questions_ai": 0,
            "questions_heur": 0,
            "questions_fallback": 0,
            "ollama_failures": 0,
            "hf_router_failures": 0,
            "openrouter_failures": 0,
            "needs_regen": 0,
            "needs_regen_db": 0,
        }

        # Product rule: each lesson must have exactly 5 questions.
        tq = 5

        # Product rule: the queue must never hang.
        # Enforce a per-lesson AI time budget; if exceeded, fall back to heuristic.
        ai_budget_seconds_per_lesson = 90.0

        for si, sub in enumerate(subs, start=1):
            _cancel_checkpoint(stage="lesson")
            title = str(sub.title or f"Урок {si}")
            text = str(sub.content or "")

            _set_job_stage(stage="ai", detail=f"{si}/{len(subs)}: {title}")
            _job_heartbeat(detail=f"{si}/{len(subs)}: {title}")
            ollama_debug: dict[str, object] = {}
            provider_order = None
            try:
                provider_order = choose_llm_provider_order_fast(ttl_seconds=300, use_cache=False)
            except Exception:
                provider_order = None
            qs: list[object] = []
            ai_elapsed_s = 0.0
            try:
                t0 = datetime.utcnow()
                qs = generate_quiz_questions_ai(
                    title=title,
                    text=text,
                    n_questions=int(tq),
                    min_questions=int(tq),
                    retries=5,
                    backoff_seconds=0.9,
                    debug_out=ollama_debug,
                    provider_order=provider_order,
                )
                ai_elapsed_s = max(0.0, (datetime.utcnow() - t0).total_seconds())
            except Exception as e:
                qs = []
                ollama_debug.setdefault("error", f"ai_exception:{type(e).__name__}")

            try:
                provider_used = str(ollama_debug.get("provider") or "").strip() or "unknown"
                _job_heartbeat(detail=f"{si}/{len(subs)}: {title} · {provider_used} · {ai_elapsed_s:.1f}s")
            except Exception:
                pass

            try:
                if ai_elapsed_s > ai_budget_seconds_per_lesson:
                    ollama_debug.setdefault("error", f"ai_timeout_budget:{ai_elapsed_s:.1f}s")
                    qs = []
            except Exception:
                pass

            _cancel_checkpoint(stage="ai")

            ai_failed = False
            used_heuristic = False

            if not qs:
                reason = str(ollama_debug.get("provider_error") or ollama_debug.get("error") or "unknown")
                perr = str(ollama_debug.get("provider_error") or "")
                # Keep last AI error visible in report for debugging.
                report["last_ai_error"] = reason
                report["last_ai_provider_error"] = perr
                if "ollama:" in perr or perr.startswith("ollama"):
                    report["ollama_failures"] = int(report.get("ollama_failures") or 0) + 1
                if "hf_router:" in perr or perr.startswith("hf_router") or perr.startswith("hf"):
                    report["hf_router_failures"] = int(report.get("hf_router_failures") or 0) + 1
                if "openrouter:" in perr or perr.startswith("openrouter") or perr.startswith("or"):
                    report["openrouter_failures"] = int(report.get("openrouter_failures") or 0) + 1
                provider_used = str(ollama_debug.get("provider") or "").strip() or "unknown"
                _set_job_stage(stage="fallback", detail=f"{si}/{len(subs)}: {provider_used}: {reason}")
                try:
                    log.warning("regen ai empty module_id=%s sub_id=%s provider_used=%s reason=%s perr=%s", str(module_id), str(sub.id), provider_used, reason, perr)
                except Exception:
                    pass
                ai_failed = True
                report["needs_regen"] = int(report.get("needs_regen") or 0) + 1

                generated = generate_quiz_questions_heuristic(
                    seed=f"regen:{m.id}:{sub.id}",
                    title=title,
                    theory_text=text,
                    target=int(tq),
                )
                if generated:
                    used_heuristic = True
                    qs = []
                    for mcq in generated:
                        qs.append(
                            type(
                                "_Q",
                                (),
                                {
                                    "type": mcq.qtype,
                                    "prompt": mcq.prompt,
                                    "correct_answer": mcq.correct_answer,
                                    "explanation": None,
                                },
                            )
                        )
                else:
                    qs = []

            _set_job_stage(stage="replace", detail=f"{si}/{len(subs)}: {title}")
            _cancel_checkpoint(stage="replace")
            # IMPORTANT: never delete old questions during regeneration.
            # QuizAttemptAnswer has FK to Question.id, so deletions can break attempt history.
            # Instead we version quizzes: create a new quiz, attach to the lesson, and write new questions there.
            lesson_quiz = Quiz(type=QuizType.submodule, pass_threshold=70, time_limit=None, attempts_limit=3)
            db.add(lesson_quiz)
            db.flush()
            sub.quiz_id = lesson_quiz.id
            db.add(sub)
            qid = lesson_quiz.id

            if qs:
                for qi, q in enumerate(qs, start=1):
                    if qi == 1 or qi % 2 == 0:
                        _job_heartbeat(detail=f"{si}/{len(subs)}: {title} · вопрос {qi}/{len(qs)}")
                    raw_type = str(getattr(q, "type", "") or "").strip().lower()
                    if raw_type == "multi":
                        qt = QuestionType.multi
                    elif raw_type == "case":
                        qt = QuestionType.case
                    else:
                        qt = QuestionType.single
                    db.add(
                        Question(
                            quiz_id=qid,
                            type=qt,
                            difficulty=2 if qt == QuestionType.multi else 1,
                            prompt=str(getattr(q, "prompt", "") or ""),
                            correct_answer=str(getattr(q, "correct_answer", "") or ""),
                            explanation=(str(getattr(q, "explanation", "")) if getattr(q, "explanation", None) else None),
                            concept_tag=(
                                f"needs_regen:regen:{m.id}:{sub.order}:{qi}" if ai_failed else f"regen:{m.id}:{sub.order}:{qi}"
                            ),
                            variant_group=None,
                        )
                    )
                report["questions_total"] = int(report.get("questions_total") or 0) + int(len(qs))
                if used_heuristic:
                    report["questions_heur"] = int(report.get("questions_heur") or 0) + int(len(qs))
                elif not ai_failed:
                    report["questions_ai"] = int(report.get("questions_ai") or 0) + int(len(qs))
            else:
                db.add(
                    Question(
                        quiz_id=qid,
                        type=QuestionType.single,
                        difficulty=1,
                        prompt=(
                            f"По уроку «{title}» выберите верный вариант.\n"
                            "A) Подтвердить прочтение и пройти квиз\nB) Пропустить урок\nC) Завершить модуль без проверки\nD) Ничего не делать"
                        ),
                        correct_answer="A",
                        explanation=None,
                        concept_tag=(
                            f"needs_regen:regen:fallback:{m.id}:{sub.order}:1" if ai_failed else f"regen:fallback:{m.id}:{sub.order}:1"
                        ),
                        variant_group=None,
                    )
                )
                report["questions_fallback"] = int(report.get("questions_fallback") or 0) + 1
                report["questions_total"] = int(report.get("questions_total") or 0) + 1

        # Product rule: rebuild final quiz as 2 random questions from each lesson quiz.
        final_qid = getattr(m, "final_quiz_id", None)
        if final_qid:
            _set_job_stage(stage="replace", detail="final quiz")
            _cancel_checkpoint(stage="final")
            # Same rule: do not delete old final questions; create a new final quiz.
            final_quiz = Quiz(type=QuizType.final, pass_threshold=70, time_limit=None, attempts_limit=3)
            db.add(final_quiz)
            db.flush()
            m.final_quiz_id = final_quiz.id
            db.add(m)
            final_qid = final_quiz.id

            rng = random.Random(f"regen_final:{m.id}:{uuid.uuid4()}")
            final_added = 0
            for lqi, sub in enumerate(subs, start=1):
                if lqi == 1 or lqi % 2 == 0:
                    _job_heartbeat(detail=f"final quiz · lesson {lqi}/{len(subs)}")
                try:
                    items = (
                        db.scalars(
                            select(Question)
                            .where(Question.quiz_id == sub.quiz_id)
                            .order_by(Question.id)
                        )
                        .all()
                    )
                except Exception:
                    items = []
                pool = list(items or [])
                rng.shuffle(pool)
                for qi, src in enumerate(pool[:2], start=1):
                    db.add(
                        Question(
                            quiz_id=final_qid,
                            type=src.type,
                            difficulty=int(getattr(src, "difficulty", 1) or 1),
                            prompt=str(getattr(src, "prompt", "") or ""),
                            correct_answer=str(getattr(src, "correct_answer", "") or ""),
                            explanation=(str(getattr(src, "explanation", "")) if getattr(src, "explanation", None) else None),
                            concept_tag=f"final:from_lesson:{m.id}:{lqi}:{qi}",
                            variant_group=None,
                        )
                    )
                    final_added += 1
                    report["questions_total"] = int(report.get("questions_total") or 0) + 1

            if final_added <= 0:
                db.add(
                    Question(
                        quiz_id=final_qid,
                        type=QuestionType.single,
                        difficulty=1,
                        prompt=(
                            f"По модулю «{m.title}» выберите верный вариант.\n"
                            "A) Подтвердить прочтение и пройти финальный тест\nB) Пропустить проверку\nC) Завершить без теста\nD) Ничего не делать"
                        ),
                        correct_answer="A",
                        explanation=None,
                        concept_tag=f"needs_regen:final:fallback:{m.id}:1",
                        variant_group=None,
                    )
                )
                report["questions_fallback"] = int(report.get("questions_fallback") or 0) + 1
                report["questions_total"] = int(report.get("questions_total") or 0) + 1

        # Auto-publish only if there are no needs_regen:* questions left in DB for this module.
        # This is more reliable than using report counters (which may diverge from persisted data).
        # Important: questions are added to the session above; flush so COUNT() queries see them.
        try:
            db.flush()
        except Exception:
            pass

        needs_regen_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("needs_regen:%"))
        active_quiz_ids: list[uuid.UUID] = [sub.quiz_id for sub in (subs or []) if getattr(sub, "quiz_id", None)]
        if getattr(m, "final_quiz_id", None):
            active_quiz_ids.append(m.final_quiz_id)
        active_quiz_ids = [qid for qid in active_quiz_ids if qid is not None]

        needs_regen_db = 0
        if active_quiz_ids:
            needs_regen_db = (
                db.scalar(
                    select(func.count())
                    .select_from(Question)
                    .where(Question.quiz_id.in_(active_quiz_ids))
                    .where(needs_regen_cond)
                )
                or 0
            )

        if report is not None:
            report["needs_regen_db"] = int(needs_regen_db)

        # Visibility is controlled by admin; regeneration must not auto-publish/hide modules.

        _set_job_stage(stage="commit")
        _cancel_checkpoint(stage="commit")
        db.commit()
        _set_job_stage(stage="done", detail=str(m.id))
        return report
    except RegenCanceledError:
        try:
            db.rollback()
        except Exception:
            pass
        return {"ok": False, "canceled": True, "module_id": str(module_id)}
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        _set_job_stage(stage="failed", detail=str(e))
        _set_job_error(error=e)
        raise
    finally:
        db.close()
