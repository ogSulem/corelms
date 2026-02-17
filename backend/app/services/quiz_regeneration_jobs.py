from __future__ import annotations

from datetime import datetime
import random
import uuid

from rq import get_current_job
from sqlalchemy import delete, select
from sqlalchemy import func

from app.db.session import SessionLocal
from app.models.module import Module, Submodule
from app.models.quiz import Question, QuestionType
from app.services.llm_handler import choose_llm_provider_order_fast, generate_quiz_questions_ai
from app.services.quiz_generation import generate_quiz_questions_heuristic


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
            raise ValueError("invalid module_id") from e

        m = db.scalar(select(Module).where(Module.id == mid))
        if m is None:
            _set_job_stage(stage="failed", detail="module not found")
            raise ValueError("module not found")

        subs = db.scalars(select(Submodule).where(Submodule.module_id == m.id).order_by(Submodule.order)).all()

        _set_job_stage(stage="load", detail=f"lessons: {len(subs)}")

        report: dict[str, object] = {
            "ok": True,
            "module_id": str(m.id),
            "module_title": str(m.title),
            "lessons": int(len(subs)),
            "questions_total": 0,
            "questions_ai": 0,
            "questions_heur": 0,
            "questions_fallback": 0,
            "ollama_failures": 0,
            "hf_router_failures": 0,
            "needs_regen": 0,
        }

        # Product rule: each lesson must have exactly 5 questions.
        tq = 5

        for si, sub in enumerate(subs, start=1):
            title = str(sub.title or f"Урок {si}")
            text = str(sub.content or "")

            _set_job_stage(stage="ollama", detail=f"{si}/{len(subs)}: {title}")
            ollama_debug: dict[str, object] = {}
            provider_order = None
            try:
                provider_order = choose_llm_provider_order_fast(ttl_seconds=300, use_cache=False)
            except Exception:
                provider_order = None
            qs = generate_quiz_questions_ai(
                title=title,
                text=text,
                n_questions=int(tq),
                debug_out=ollama_debug,
                provider_order=provider_order,
            )

            ai_failed = False
            used_heuristic = False

            if not qs:
                reason = str(ollama_debug.get("provider_error") or ollama_debug.get("error") or "unknown")
                perr = str(ollama_debug.get("provider_error") or "")
                if "ollama:" in perr or perr.startswith("ollama"):
                    report["ollama_failures"] = int(report.get("ollama_failures") or 0) + 1
                if "hf_router:" in perr or perr.startswith("hf_router") or perr.startswith("hf"):
                    report["hf_router_failures"] = int(report.get("hf_router_failures") or 0) + 1
                provider_used = str(ollama_debug.get("provider") or "").strip() or "unknown"
                _set_job_stage(stage="fallback", detail=f"{si}/{len(subs)}: {provider_used}: {reason}")
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

            qid = sub.quiz_id
            if not qid:
                continue

            _set_job_stage(stage="replace", detail=f"{si}/{len(subs)}: {title}")
            db.execute(delete(Question).where(Question.quiz_id == qid))

            if qs:
                for qi, q in enumerate(qs, start=1):
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
            db.execute(delete(Question).where(Question.quiz_id == final_qid))

            rng = random.Random(f"regen_final:{m.id}:{uuid.uuid4()}")
            final_added = 0
            for lqi, sub in enumerate(subs, start=1):
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
        lesson_quiz_ids_subq = select(Submodule.quiz_id).where(Submodule.module_id == m.id).where(Submodule.quiz_id.is_not(None))
        needs_regen_by_quiz = (
            db.scalar(
                select(func.count())
                .select_from(Question)
                .where(Question.quiz_id.in_(lesson_quiz_ids_subq))
                .where(needs_regen_cond)
            )
            or 0
        )
        # Extra safety: if quiz/submodule linkage is inconsistent for any reason,
        # fall back to tag-based scan (our tags always include module id).
        needs_regen_by_tag = (
            db.scalar(
                select(func.count())
                .select_from(Question)
                .where(needs_regen_cond)
                .where(Question.concept_tag.like(f"%{m.id}%"))
            )
            or 0
        )

        needs_regen_db = max(int(needs_regen_by_quiz), int(needs_regen_by_tag))
        if getattr(m, "final_quiz_id", None):
            needs_regen_db += (
                db.scalar(
                    select(func.count())
                    .select_from(Question)
                    .where(Question.quiz_id == m.final_quiz_id)
                    .where(needs_regen_cond)
                )
                or 0
            )

        if report is not None:
            report["needs_regen_db"] = int(needs_regen_db)

        # Visibility is controlled by admin; regeneration must not auto-publish/hide modules.

        _set_job_stage(stage="commit")
        db.commit()
        _set_job_stage(stage="done", detail=str(m.id))
        return report
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
