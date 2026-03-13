from __future__ import annotations

from datetime import datetime
import random
import time
import uuid
import logging
import json

from rq import get_current_job
from sqlalchemy import delete, select
from sqlalchemy import func

from app.db.session import SessionLocal
from app.models.module import Module, Submodule
from app.models.quiz import Question, QuestionType, Quiz, QuizType
from app.services.llm_handler import choose_llm_provider_order_fast, generate_quiz_questions_ai
from app.services.quiz_generation import generate_quiz_questions_heuristic
from app.services.quiz_text import is_useful_quiz_text
from app.services.modules import modules_bump_rev
from app.core.config import settings
from app.core.redis_client import get_redis


log = logging.getLogger(__name__)


def _skip_reason_for_submodule(*, sub: Submodule, text: str) -> str | None:
    try:
        if bool(getattr(sub, "is_folder", False)):
            return "folder_lesson"
    except Exception:
        pass

    try:
        obj_key = str(getattr(sub, "content_object_key", None) or "").strip()
    except Exception:
        obj_key = ""

    useful_text = bool(is_useful_quiz_text(str(text or "")))
    if not useful_text:
        # If the lesson points to a file in storage, it's usually a file-only lesson.
        # Those should be skipped deterministically (otherwise regen tries to generate from empty placeholders).
        if obj_key:
            return "file_lesson"
        return "no_text"

    return None


def _regen_ckpt_key(*, module_id: str) -> str:
    mid = str(module_id or "").strip()
    return f"admin:regen_checkpoint:module:{mid}" if mid else "admin:regen_checkpoint:module:"


def _load_regen_checkpoint(*, module_id: str) -> dict[str, object]:
    try:
        key = _regen_ckpt_key(module_id=module_id)
        if not key or key.endswith(":"):
            return {}
        r = get_redis()
        raw = r.get(key)
        if not raw:
            return {}
        s = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _persist_regen_checkpoint(*, module_id: str, checkpoint: dict[str, object], ttl_days: int = 14) -> None:
    try:
        key = _regen_ckpt_key(module_id=module_id)
        if not key or key.endswith(":"):
            return
        r = get_redis()
        r.set(key, json.dumps(checkpoint, ensure_ascii=False))
        r.expire(key, int(max(60, min(60 * 60 * 24 * 90, int(ttl_days) * 60 * 60 * 24))))
    except Exception:
        return


def _clear_regen_checkpoint(*, module_id: str) -> None:
    try:
        key = _regen_ckpt_key(module_id=module_id)
        if not key or key.endswith(":"):
            return
        r = get_redis()
        r.delete(key)
    except Exception:
        return


def _persist_job_snapshot(*, job, meta: dict) -> None:
    try:
        job_id = str(getattr(job, "id", "") or "").strip()
        if not job_id:
            return

        result_payload = None
        try:
            st = str(job.get_status(refresh=True) or "").strip().lower()
            if st == "finished":
                res = job.result
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    result_payload = res
        except Exception:
            result_payload = None

        if isinstance(result_payload, dict):
            try:
                raw = json.dumps(result_payload, ensure_ascii=False)
                if len(raw) > 200_000:
                    result_payload = {"ok": bool(result_payload.get("ok", True)), "module_id": result_payload.get("module_id")}
            except Exception:
                result_payload = None

        payload = {
            "id": job_id,
            "status": str(job.get_status(refresh=True) or ""),
            "enqueued_at": job.enqueued_at.isoformat() if getattr(job, "enqueued_at", None) else None,
            "started_at": job.started_at.isoformat() if getattr(job, "started_at", None) else None,
            "ended_at": job.ended_at.isoformat() if getattr(job, "ended_at", None) else None,
            "queue": str(getattr(job, "origin", "") or "").strip() or None,
            "meta": meta,
            "result": result_payload,
            "ts": datetime.utcnow().isoformat(),
        }
        r = get_redis()
        r.set(f"admin:job_snapshot:{job_id}", json.dumps(payload, ensure_ascii=False))
        r.expire(f"admin:job_snapshot:{job_id}", 60 * 60 * 24 * 30)
    except Exception:
        return


def _bump_admin_jobs_rev() -> None:
    try:
        r = get_redis()
        r.incr("admin:jobs:rev")
        try:
            r.expire("admin:jobs:rev", 60 * 60 * 24 * 30)
        except Exception:
            log.debug("_bump_admin_jobs_rev: expire failed", exc_info=True)
    except Exception:
        return


def _publish_admin_jobs_changed(*, job) -> None:
    try:
        r = get_redis()
        _bump_admin_jobs_rev()
        r.publish("admin:jobs:changed", str(getattr(job, "id", "") or "1"))
    except Exception:
        return


def _publish_admin_jobs_changed_throttled(*, job, meta: dict, force: bool = False) -> None:
    try:
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        last_ms = 0
        try:
            last_ms = int(meta.get("_admin_jobs_pub_at_ms") or 0)
        except Exception:
            last_ms = 0
        if (not force) and last_ms and (now_ms - last_ms) < 1000:
            return
        meta["_admin_jobs_pub_at_ms"] = now_ms
        _publish_admin_jobs_changed(job=job)
    except Exception:
        return


def _snip(v: object, *, limit: int) -> str | None:
    try:
        s = str(v or "")
    except Exception:
        return None
    s = s.strip()
    if not s:
        return None
    if limit and len(s) > int(limit):
        return s[: int(limit)] + "…"
    return s


def _persist_llm_debug(*, entry: dict[str, object]) -> None:
    allow_save = bool(getattr(settings, "llm_debug_save", False))
    allow_log = bool(getattr(settings, "llm_debug_log", False))

    if not allow_save and not allow_log:
        return

    if allow_save:
        try:
            job = get_current_job()
        except Exception:
            job = None
        if job is not None:
            try:
                meta = dict(job.meta or {})
                items = list(meta.get("llm_debug") or [])
                items.append(entry)
                # Keep only the last N entries to avoid unbounded growth.
                meta["llm_debug"] = items[-50:]
                _publish_admin_jobs_changed_throttled(job=job, meta=meta, force=False)
                job.meta = meta
                job.save_meta()
                _persist_job_snapshot(job=job, meta=meta)
            except Exception:
                pass

    if allow_log:
        # Always mirror debug into logs (truncated by _snip upstream).
        try:
            log.info("LLM_DEBUG %s", entry)
        except Exception:
            pass


def _ai_generate_questions_best_effort(
    *,
    title: str,
    text: str,
    target_questions: int,
    provider_order,
    time_budget_seconds: float,
    attempts: int = 3,
    attempt_sleep_seconds: float = 1.5,
) -> tuple[list[object], dict[str, object], float, int]:
    qs: list[object] = []
    llm_debug: dict[str, object] = {}
    ai_elapsed_s = 0.0
    used_attempt = 1

    tries = max(1, min(int(attempts or 3), 6))
    for attempt in range(1, tries + 1):
        used_attempt = attempt
        llm_debug = {"attempt": attempt, "attempts_total": tries}
        try:
            t0 = datetime.utcnow()
            qs = generate_quiz_questions_ai(
                title=title,
                text=text,
                n_questions=int(target_questions),
                min_questions=int(target_questions),
                # Internal retries inside LLM call (connect timeouts etc.)
                retries=5,
                backoff_seconds=1.0,
                debug_out=llm_debug,
                provider_order=provider_order,
                # Give more room for slow providers.
                time_budget_seconds=float(max(30.0, float(time_budget_seconds or 0.0))),
            )
            ai_elapsed_s = max(0.0, (datetime.utcnow() - t0).total_seconds())
        except Exception as e:
            qs = []
            llm_debug.setdefault("error", f"ai_exception:{type(e).__name__}")

        if qs:
            break

        # Backoff between attempts.
        try:
            sl = float(attempt_sleep_seconds) * float(attempt)
            sl = max(0.0, min(sl, 12.0))
            time.sleep(sl)
        except Exception:
            pass

    return qs, llm_debug, float(ai_elapsed_s), int(used_attempt)


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
        _publish_admin_jobs_changed_throttled(job=job, meta=meta, force=True)
        job.meta = meta
        job.save_meta()
        _persist_job_snapshot(job=job, meta=meta)
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
        _publish_admin_jobs_changed_throttled(job=job, meta=meta, force=False)
        job.meta = meta
        job.save_meta()
        _persist_job_snapshot(job=job, meta=meta)
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


def _set_job_error(*, error: Exception, error_code: str = "REGEN_FAILED", error_hint: str | None = None) -> None:
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
        _publish_admin_jobs_changed_throttled(job=job, meta=meta, force=True)
        job.meta = meta
        job.save_meta()
        _persist_job_snapshot(job=job, meta=meta)
    except Exception:
        return


def _submodule_is_ok(*, db: Session, sub: Submodule, target_questions: int) -> bool:
    try:
        qid = getattr(sub, "quiz_id", None)
        if not qid:
            return False
        needs_regen_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("needs_regen:%"))
        needs = db.scalar(select(func.count()).select_from(Question).where(Question.quiz_id == qid).where(needs_regen_cond)) or 0
        total = db.scalar(select(func.count()).select_from(Question).where(Question.quiz_id == qid)) or 0
        return int(needs) <= 0 and int(total) >= int(target_questions)
    except Exception:
        return False


def regenerate_submodule_quiz_job(
    *,
    submodule_id: str,
    target_questions: int = 5,
    force: bool = True,
) -> dict:
    _set_job_stage(stage="start", detail=str(submodule_id))
    db = SessionLocal()
    try:
        try:
            _job = get_current_job()
        except Exception:
            _job = None
        job_seed = str(getattr(_job, "id", "") or "").strip() or datetime.utcnow().isoformat()

        sid_raw = str(submodule_id).strip()
        try:
            sid = uuid.UUID(sid_raw)
        except Exception as e:
            _set_job_stage(stage="failed", detail="invalid submodule_id")
            _set_job_error(
                error=e,
                error_code="INVALID_SUBMODULE_ID",
                error_hint="Неверный submodule_id (UUID).",
            )
            raise ValueError("invalid submodule_id") from e

        sub = db.scalar(select(Submodule).where(Submodule.id == sid))
        if sub is None:
            _set_job_stage(stage="failed", detail="submodule not found")
            _set_job_error(
                error=ValueError("submodule not found"),
                error_code="SUBMODULE_NOT_FOUND",
                error_hint="Подмодуль не найден в базе.",
            )
            raise ValueError("submodule not found")

        m = db.scalar(select(Module).where(Module.id == sub.module_id))
        if m is None:
            _set_job_stage(stage="failed", detail="module not found")
            _set_job_error(
                error=ValueError("module not found"),
                error_code="MODULE_NOT_FOUND",
                error_hint="Модуль для подмодуля не найден.",
            )
            raise ValueError("module not found")

        # Enrich meta for UI.
        try:
            job = get_current_job()
            if job is not None:
                meta = dict(job.meta or {})
                meta.setdefault("job_kind", "regen")
                meta["module_id"] = str(m.id)
                meta["module_title"] = str(m.title)
                meta["submodule_id"] = str(sub.id)
                meta["submodule_title"] = str(sub.title or "")
                meta["target_questions"] = int(target_questions)
                job.meta = meta
                job.save_meta()
        except Exception:
            pass

        if (not force) and _submodule_is_ok(db=db, sub=sub, target_questions=int(target_questions)):
            _set_job_stage(stage="done", detail="already_ok")
            try:
                _persist_llm_debug(
                    entry={
                        "ts": datetime.utcnow().isoformat(),
                        "kind": "regen",
                        "module_id": str(m.id),
                        "submodule_id": str(sub.id),
                        "submodule_title": str(sub.title or ""),
                        "provider": "skip",
                        "skip_reason": "already_ok",
                        "target_questions": int(target_questions),
                    }
                )
            except Exception:
                pass
            return {
                "ok": True,
                "skipped": True,
                "module_id": str(m.id),
                "submodule_id": str(sub.id),
            }

        # Keep in sync with module regen per-lesson budget for consistent behavior.
        ai_budget_seconds = 300.0

        # Reuse module regen logic for a single lesson.
        subs = [sub]
        tq = max(1, int(target_questions or 5))
        report: dict[str, object] = {
            "ok": True,
            "module_id": str(m.id),
            "module_title": str(m.title),
            "submodule_id": str(sub.id),
            "submodule_title": str(sub.title or ""),
            "lessons": 1,
            "questions_total": 0,
            "questions_ai": 0,
            "questions_heur": 0,
            "questions_fallback": 0,
            "needs_regen": 0,
            "needs_regen_db": 0,
        }

        for si, sub in enumerate(subs, start=1):
            _cancel_checkpoint(stage="lesson")
            title = str(sub.title or "Урок")
            text = str(sub.content or "")
            # Keep prompts small for speed and to reduce LLM latency.
            text = text[:8000]

            skip_reason = _skip_reason_for_submodule(sub=sub, text=text)
            if skip_reason:
                _set_job_stage(stage="skip", detail=f"SKIP: {title} · {skip_reason}")
                _job_heartbeat(detail=f"SKIP: {title} · {skip_reason}")
                try:
                    _persist_llm_debug(
                        entry={
                            "ts": datetime.utcnow().isoformat(),
                            "kind": "regen",
                            "module_id": str(m.id),
                            "submodule_id": str(sub.id),
                            "submodule_title": str(title),
                            "provider": "skip",
                            "skip_reason": str(skip_reason),
                            "target_questions": int(tq),
                        }
                    )
                except Exception:
                    pass
                _set_job_stage(stage="done", detail=f"skipped:{skip_reason}")
                return {
                    "ok": True,
                    "skipped": True,
                    "skip_reason": str(skip_reason),
                    "module_id": str(m.id),
                    "submodule_id": str(sub.id),
                }

            _set_job_stage(stage="ai", detail=f"1/1: {title}")
            _job_heartbeat(detail=f"AI 1/1: {title}")
            provider_order = None
            try:
                provider_order = choose_llm_provider_order_fast(ttl_seconds=300, use_cache=True)
            except Exception:
                provider_order = None
            qs, llm_debug, ai_elapsed_s, _attempt_used = _ai_generate_questions_best_effort(
                title=title,
                text=text,
                target_questions=int(tq),
                provider_order=provider_order,
                time_budget_seconds=float(ai_budget_seconds),
                attempts=3,
                attempt_sleep_seconds=1.5,
            )

            # Persist debug info (prompt/response snippets) to job meta for /admin/jobs.
            try:
                limit = int(getattr(settings, "llm_debug_max_chars", 2000) or 2000)
            except Exception:
                limit = 2000
            try:
                req = llm_debug.get("request") if isinstance(llm_debug, dict) else None
                req_obj = req if isinstance(req, dict) else {}
                entry: dict[str, object] = {
                    "ts": datetime.utcnow().isoformat(),
                    "kind": "regen",
                    "module_id": str(m.id),
                    "submodule_id": str(sub.id),
                    "submodule_title": str(title),
                    "provider": str(llm_debug.get("provider") or ""),
                    "attempt": int(llm_debug.get("attempt") or 1),
                    "attempts_total": int(llm_debug.get("attempts_total") or 1),
                    "provider_error": str(llm_debug.get("provider_error") or ""),
                    "error": str(llm_debug.get("error") or ""),
                    "ai_elapsed_s": float(ai_elapsed_s),
                    "system_prompt_snip": _snip(req_obj.get("system_prompt_snip"), limit=limit),
                    "user_prompt_snip": _snip(req_obj.get("user_prompt_snip"), limit=limit),
                    "raw_snip": _snip(llm_debug.get("raw"), limit=limit),
                    "repair_used": bool(llm_debug.get("repair_used")) if isinstance(llm_debug, dict) else False,
                    "used_heuristic": False,
                    "questions_count": int(len(qs or [])),
                }
                _persist_llm_debug(entry=entry)
            except Exception:
                log.debug("regenerate_submodule_quiz_job: failed to persist llm debug", exc_info=True)

            try:
                provider_used = str(llm_debug.get("provider") or "").strip() or "unknown"
                _job_heartbeat(detail=f"1/1: {title} · {provider_used} · {ai_elapsed_s:.1f}s")
            except Exception:
                pass

            try:
                if ai_elapsed_s > ai_budget_seconds:
                    llm_debug.setdefault("error", f"ai_timeout_budget:{ai_elapsed_s:.1f}s")
                    qs = []
            except Exception:
                pass

            _cancel_checkpoint(stage="ai")
            ai_failed = False
            used_heuristic = False

            if not qs:
                ai_failed = True
                report["needs_regen"] = int(report.get("needs_regen") or 0) + 1

                generated = generate_quiz_questions_heuristic(
                    seed=f"regen:{job_seed}:{m.id}:{sub.id}",
                    title=title,
                    theory_text=text,
                    target=int(tq),
                )
                if generated:
                    used_heuristic = True
                    try:
                        _persist_llm_debug(
                            entry={
                                "ts": datetime.utcnow().isoformat(),
                                "kind": "regen",
                                "module_id": str(m.id),
                                "submodule_id": str(sub.id),
                                "submodule_title": str(title),
                                "provider": "heuristic",
                                "error": "ai_failed" if ai_failed else "",
                                "used_heuristic": True,
                                "questions_count": int(len(generated or [])),
                            }
                        )
                    except Exception:
                        pass
                    try:
                        # Hint for UI: heuristic was used because AI failed.
                        _set_job_stage(stage="ai", detail=f"1/1: {title} · heuristic")
                    except Exception:
                        pass
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

            _set_job_stage(stage="replace", detail=f"1/1: {title}")
            _cancel_checkpoint(stage="replace")
            _job_heartbeat(detail=f"WRITE 1/1: {title}")
            lesson_quiz = Quiz(type=QuizType.submodule, pass_threshold=70, time_limit=None, attempts_limit=3)
            db.add(lesson_quiz)
            db.flush()
            sub.quiz_id = lesson_quiz.id
            db.add(sub)
            qid = lesson_quiz.id

            try:
                # Expose before/after info for debugging in admin UI (/admin/jobs/{id}).
                job = get_current_job()
                if job is not None:
                    meta = dict(job.meta or {})
                    meta.setdefault("regen_lessons", [])
                    lessons_meta = list(meta.get("regen_lessons") or [])
                    lessons_meta.append(
                        {
                            "submodule_id": str(sub.id),
                            "submodule_title": str(title),
                            "old_quiz_id": old_quiz_id,
                            "old_questions": int(old_questions_count),
                            "new_quiz_id": str(qid),
                            "ai_failed": bool(ai_failed),
                            "used_heuristic": bool(used_heuristic),
                            "questions_written": int(len(qs or []) or 1),
                        }
                    )
                    meta["regen_lessons"] = lessons_meta[-200:]
                    job.meta = meta
                    job.save_meta()
            except Exception:
                log.debug("regenerate_submodule_quiz_job: failed to save job meta", exc_info=True)

            if qs:
                for qi, q in enumerate(qs, start=1):
                    raw_type = str(getattr(q, "type", "") or "").strip().lower()
                    if raw_type == "multi":
                        qt = QuestionType.multi
                    elif raw_type == "case":
                        qt = QuestionType.case
                    else:
                        qt = QuestionType.single

                    # Unify question quality tags:
                    # - ok:* means the question is considered usable
                    # - needs_regen:* means it should be regenerated/improved later
                    if used_heuristic:
                        tag = f"heur:regen:{m.id}:{sub.order}:{qi}"
                    elif ai_failed:
                        tag = f"needs_regen:regen:{m.id}:{sub.order}:{qi}"
                    else:
                        tag = f"ok:regen:{m.id}:{sub.order}:{qi}"
                    db.add(
                        Question(
                            quiz_id=qid,
                            type=qt,
                            difficulty=2 if qt == QuestionType.multi else 1,
                            prompt=str(getattr(q, "prompt", "") or ""),
                            correct_answer=str(getattr(q, "correct_answer", "") or ""),
                            explanation=(str(getattr(q, "explanation", "")) if getattr(q, "explanation", None) else None),
                            concept_tag=tag,
                            variant_group=None,
                        )
                    )
                report["questions_total"] = int(report.get("questions_total") or 0) + int(len(qs))
                if used_heuristic:
                    report["questions_heur"] = int(report.get("questions_heur") or 0) + int(len(qs))
                elif not ai_failed:
                    report["questions_ai"] = int(report.get("questions_ai") or 0) + int(len(qs))
                report["lessons_ok"] = int(report.get("lessons_ok") or 0) + 1
            else:
                # Partial success policy: never fail the whole module regen because one lesson failed.
                # Also: do NOT create an empty quiz. Keep the old quiz_id (if any) intact.
                report["lessons_failed"] = int(report.get("lessons_failed") or 0) + 1
                report["needs_regen"] = int(report.get("needs_regen") or 0) + 1
                try:
                    provider_used = str(llm_debug.get("provider") or "").strip() or "unknown"
                    reason = str(llm_debug.get("provider_error") or llm_debug.get("error") or "empty")
                    _persist_llm_debug(
                        entry={
                            "ts": datetime.utcnow().isoformat(),
                            "kind": "regen",
                            "module_id": str(m.id),
                            "submodule_id": str(sub.id),
                            "submodule_title": str(title),
                            "provider": provider_used,
                            "error": "lesson_failed_empty",
                            "provider_error": reason,
                            "questions_count": 0,
                        }
                    )
                except Exception:
                    pass
                _job_heartbeat(detail=f"FAIL {si_eff}/{int(effective_total)}: {title} · empty")
                continue

            try:
                db.flush()
            except Exception:
                pass
            _job_heartbeat(detail=f"DONE 1/1: {title}")

        # needs_regen_db for this submodule only
        try:
            needs_regen_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("needs_regen:%"))
            if getattr(sub, "quiz_id", None):
                report["needs_regen_db"] = int(
                    db.scalar(
                        select(func.count()).select_from(Question).where(Question.quiz_id == sub.quiz_id).where(needs_regen_cond)
                    )
                    or 0
                )
        except Exception:
            pass

        _set_job_stage(stage="commit")
        _cancel_checkpoint(stage="commit")
        db.commit()
        _set_job_stage(stage="done", detail=str(sub.id))
        return report
    except RegenCanceledError:
        try:
            db.rollback()
        except Exception:
            log.debug("regenerate_submodule_quiz_job: db rollback failed on cancel", exc_info=True)
        return {"ok": False, "canceled": True, "submodule_id": str(submodule_id)}
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            log.debug("regenerate_submodule_quiz_job: db rollback failed", exc_info=True)
        _set_job_stage(stage="failed", detail=str(e))
        _set_job_error(error=e)
        raise
    finally:
        db.close()


def regenerate_module_quizzes_job(
    *,
    module_id: str,
    target_questions: int = 5,
    only_missing: bool = True,
) -> dict:
    _set_job_stage(stage="start", detail=str(module_id))

    db = SessionLocal()
    try:
        try:
            _job = get_current_job()
        except Exception:
            _job = None
        job_seed = str(getattr(_job, "id", "") or "").strip() or datetime.utcnow().isoformat()

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

        # Full regen must not be affected by any previous resume checkpoint.
        # Otherwise an old checkpoint (from a canceled or previous run) can make a new regen
        # appear as if it processed only 1 lesson.
        if not bool(only_missing):
            try:
                _clear_regen_checkpoint(module_id=str(m.id))
            except Exception:
                log.debug("regenerate_module_quizzes_job: failed to clear regen checkpoint", exc_info=True)

        subs_all = db.scalars(select(Submodule).where(Submodule.module_id == m.id).order_by(Submodule.order)).all()

        ckpt = _load_regen_checkpoint(module_id=str(m.id))
        done_ids: set[str] = set()
        try:
            raw_done = ckpt.get("done_submodule_ids")
            if isinstance(raw_done, list):
                for x in raw_done:
                    s = str(x or "").strip()
                    if s:
                        done_ids.add(s)
        except Exception:
            done_ids = set()

        try:
            effective_total = 0
            for _sub in list(subs_all or []):
                try:
                    _text = str(getattr(_sub, "content", "") or "")
                    _skip_reason = _skip_reason_for_submodule(sub=_sub, text=_text)
                    # Count only lessons that we will actually process.
                    if not _skip_reason:
                        effective_total += 1
                except Exception:
                    effective_total += 1
        except Exception:
            effective_total = int(len(subs_all or []))

        _set_job_stage(stage="load", detail=f"lessons: {int(len(subs_all))} (quiz: {int(effective_total)})")
        _cancel_checkpoint(stage="load")

        report: dict[str, object] = {
            "ok": True,
            "module_id": str(module_id),
            "module_title": str(m.title),
            "lessons": int(effective_total),
            "lessons_ok": 0,
            "lessons_failed": 0,
            "lessons_skipped": 0,
            "questions_total": 0,
            "questions_ai": 0,
            "questions_heur": 0,
            "questions_fallback": 0,
            "openrouter_failures": 0,
            "needs_regen": 0,
            "needs_regen_db": 0,
        }

        # Product rule: each lesson must have exactly 5 questions.
        tq = 5

        # Per-lesson AI time budget; tune as needed.
        try:
            ai_budget_seconds_per_lesson = float(getattr(settings, "regen_ai_budget_seconds_per_lesson", None) or 0) or 300.0
        except Exception:
            ai_budget_seconds_per_lesson = 300.0
        try:
            max_lesson_attempts = int(getattr(settings, "regen_max_lesson_attempts", None) or 0) or 2
        except Exception:
            max_lesson_attempts = 2
        max_lesson_attempts = max(1, min(6, int(max_lesson_attempts)))

        si_eff = 0
        for _si_raw, sub in enumerate(subs_all, start=1):
            _cancel_checkpoint(stage="lesson")
            title = str(sub.title or f"Урок {_si_raw}")
            text = str(sub.content or "")
            # Keep prompts small for speed and to reduce LLM latency.
            text = text[:8000]

            sub_id_str = str(getattr(sub, "id", "") or "").strip()
            if sub_id_str and sub_id_str in done_ids:
                # Resume: this lesson was already committed in a previous run.
                si_eff += 1
                _set_job_stage(stage="skip", detail=f"RESUME {si_eff}/{int(effective_total)}: {title}")
                _job_heartbeat(detail=f"RESUME {si_eff}/{int(effective_total)}: {title}")
                report["lessons_ok"] = int(report.get("lessons_ok") or 0) + 1
                continue

            old_quiz_id = None
            try:
                old_quiz_id = str(getattr(sub, "quiz_id", None) or "") or None
            except Exception:
                old_quiz_id = None
            old_questions_count = 0
            if old_quiz_id:
                try:
                    old_questions_count = int(
                        db.scalar(select(func.count()).select_from(Question).where(Question.quiz_id == sub.quiz_id)) or 0
                    )
                except Exception:
                    old_questions_count = 0

            requires_quiz = bool(getattr(sub, "requires_quiz", True))
            useful_text = bool(is_useful_quiz_text(text))

            skip_reason = _skip_reason_for_submodule(sub=sub, text=text)
            if skip_reason:
                _set_job_stage(stage="skip", detail=f"SKIP: {title} · {skip_reason}")
                _job_heartbeat(detail=f"SKIP: {title} · {skip_reason}")
                try:
                    _persist_llm_debug(
                        entry={
                            "ts": datetime.utcnow().isoformat(),
                            "kind": "regen",
                            "module_id": str(m.id),
                            "submodule_id": str(sub.id),
                            "submodule_title": str(title),
                            "provider": "skip",
                            "skip_reason": str(skip_reason),
                        }
                    )
                except Exception:
                    pass
                report["lessons_skipped"] = int(report.get("lessons_skipped") or 0) + 1
                continue

            if (not requires_quiz) and (not useful_text):
                _set_job_stage(stage="skip", detail=f"SKIP: {title} · materials_only")
                _job_heartbeat(detail=f"SKIP: {title} · materials_only")
                try:
                    _persist_llm_debug(
                        entry={
                            "ts": datetime.utcnow().isoformat(),
                            "kind": "regen",
                            "module_id": str(m.id),
                            "submodule_id": str(sub.id),
                            "submodule_title": str(title),
                            "provider": "skip",
                            "skip_reason": "materials_only",
                        }
                    )
                except Exception:
                    pass
                report["lessons_skipped"] = int(report.get("lessons_skipped") or 0) + 1
                continue

            if (not requires_quiz) and useful_text:
                # Legacy/edge-case: lesson marked as file-only but has enough text to generate quiz.
                # Flip flag so future imports/regens behave consistently.
                try:
                    sub.requires_quiz = True
                    db.add(sub)
                    db.flush()
                    requires_quiz = True
                except Exception:
                    pass

            if bool(only_missing) and _submodule_is_ok(db=db, sub=sub, target_questions=int(tq)):
                si_eff += 1
                _set_job_stage(stage="skip", detail=f"{si_eff}/{int(effective_total)}: {title}")
                _job_heartbeat(detail=f"SKIP {si_eff}/{int(effective_total)}: {title}")
                try:
                    _persist_llm_debug(
                        entry={
                            "ts": datetime.utcnow().isoformat(),
                            "kind": "regen",
                            "module_id": str(m.id),
                            "submodule_id": str(sub.id),
                            "submodule_title": str(title),
                            "provider": "skip",
                            "skip_reason": "already_ok",
                            "target_questions": int(tq),
                        }
                    )
                except Exception:
                    pass
                report["lessons_skipped"] = int(report.get("lessons_skipped") or 0) + 1
                continue

            si_eff += 1
            _set_job_stage(stage="ai", detail=f"{si_eff}/{int(effective_total)}: {title}")
            _job_heartbeat(detail=f"AI {si_eff}/{int(effective_total)}: {title}")

            provider_order = None
            try:
                provider_order = choose_llm_provider_order_fast(ttl_seconds=300, use_cache=True)
            except Exception:
                provider_order = None

            # Per-lesson retry loop (so 1 bad lesson doesn't ruin the whole module regen).
            qs: list[object] = []
            llm_debug: dict[str, object] = {}
            ai_elapsed_s = 0.0
            for lesson_attempt in range(1, max_lesson_attempts + 1):
                llm_debug = {}
                try:
                    t0 = datetime.utcnow()
                    qs, llm_debug, ai_elapsed_s, _attempt_used = _ai_generate_questions_best_effort(
                        title=title,
                        text=text,
                        target_questions=int(tq),
                        provider_order=provider_order,
                        time_budget_seconds=float(ai_budget_seconds_per_lesson),
                        attempts=3,
                        attempt_sleep_seconds=1.5,
                    )
                    ai_elapsed_s = max(0.0, (datetime.utcnow() - t0).total_seconds())
                except Exception as e:
                    qs = []
                    llm_debug.setdefault("error", f"ai_exception:{type(e).__name__}")

                if qs:
                    break

                # If AI returned empty and we still have attempts, jitter and retry.
                if lesson_attempt < max_lesson_attempts:
                    try:
                        time.sleep(0.3 + random.random() * 0.35)
                    except Exception:
                        pass

            try:
                provider_used = str(llm_debug.get("provider") or "").strip() or "unknown"
                _job_heartbeat(detail=f"{si_eff}/{int(effective_total)}: {title} · {provider_used} · {ai_elapsed_s:.1f}s")
            except Exception:
                pass

            try:
                if ai_elapsed_s > ai_budget_seconds_per_lesson:
                    llm_debug.setdefault("error", f"ai_timeout_budget:{ai_elapsed_s:.1f}s")
                    qs = []
            except Exception:
                pass

            _cancel_checkpoint(stage="ai")

            ai_failed = False
            used_heuristic = False

            if not qs:
                reason = str(llm_debug.get("provider_error") or llm_debug.get("error") or "unknown")
                perr = str(llm_debug.get("provider_error") or "")
                # Keep last AI error visible in report for debugging.
                report["last_ai_error"] = reason
                report["last_ai_provider_error"] = perr
                if "openrouter:" in perr or perr.startswith("openrouter") or perr.startswith("or"):
                    report["openrouter_failures"] = int(report.get("openrouter_failures") or 0) + 1
                provider_used = str(llm_debug.get("provider") or "").strip() or "unknown"
                if provider_used == "unknown":
                    # provider may be missing in some failure modes; infer from provider_error
                    if perr.startswith("openrouter") or "openrouter" in perr:
                        provider_used = "openrouter"
                _set_job_stage(stage="fallback", detail=f"{si_eff}/{int(effective_total)}: {provider_used}: {reason}")
                try:
                    log.warning("regen ai empty module_id=%s sub_id=%s provider_used=%s reason=%s perr=%s", str(module_id), str(sub.id), provider_used, reason, perr)
                except Exception:
                    pass
                ai_failed = True
                report["needs_regen"] = int(report.get("needs_regen") or 0) + 1

                generated = generate_quiz_questions_heuristic(
                    seed=f"regen:{job_seed}:{m.id}:{sub.id}",
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

            try:
                want_q = int(tq)
            except Exception:
                want_q = 0
            want_q = max(1, int(want_q or 1))
            if qs and len(qs) < want_q:
                try:
                    missing = int(want_q - len(qs))
                except Exception:
                    missing = 0
                if missing > 0:
                    try:
                        generated_more = generate_quiz_questions_heuristic(
                            seed=f"regen:fill:{job_seed}:{m.id}:{sub.id}:{len(qs)}",
                            title=title,
                            theory_text=text,
                            target=int(missing),
                        )
                    except Exception:
                        generated_more = []
                    if generated_more:
                        used_heuristic = True
                        seen_prompts: set[str] = set()
                        try:
                            for q0 in qs:
                                p0 = str(getattr(q0, "prompt", "") or "").strip()
                                if p0:
                                    seen_prompts.add(p0)
                        except Exception:
                            seen_prompts = set()
                        for mcq in generated_more:
                            if len(qs) >= want_q:
                                break
                            try:
                                p = str(getattr(mcq, "prompt", "") or "").strip()
                                if p and p in seen_prompts:
                                    continue
                                if p:
                                    seen_prompts.add(p)
                            except Exception:
                                pass
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

            try:
                if qs:
                    _set_job_stage(stage="replace", detail=f"{si_eff}/{int(effective_total)}: {title}")
                    _cancel_checkpoint(stage="replace")
                    _job_heartbeat(detail=f"WRITE {si_eff}/{int(effective_total)}: {title}")
                    # IMPORTANT: never delete old questions during regeneration.
                    # QuizAttemptAnswer has FK to Question.id, so deletions can break attempt history.
                    # Instead we version quizzes: create a new quiz, attach to the lesson, and write new questions there.
                    lesson_quiz = Quiz(type=QuizType.submodule, pass_threshold=70, time_limit=None, attempts_limit=3)
                    db.add(lesson_quiz)
                    db.flush()
                    sub.quiz_id = lesson_quiz.id
                    db.add(sub)
                    qid = lesson_quiz.id

                    for qi, q in enumerate(qs, start=1):
                        if qi == 1 or qi % 2 == 0:
                            _job_heartbeat(detail=f"{si_eff}/{int(effective_total)}: {title} · вопрос {qi}/{len(qs)}")
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
                                    f"heur:regen:{m.id}:{sub.order}:{qi}"
                                    if used_heuristic
                                    else (
                                        f"needs_regen:regen:{m.id}:{sub.order}:{qi}" if ai_failed else f"ok:regen:{m.id}:{sub.order}:{qi}"
                                    )
                                ),
                                variant_group=None,
                            )
                        )

                    report["questions_total"] = int(report.get("questions_total") or 0) + int(len(qs))
                    if used_heuristic:
                        report["questions_heur"] = int(report.get("questions_heur") or 0) + int(len(qs))
                    elif not ai_failed:
                        report["questions_ai"] = int(report.get("questions_ai") or 0) + int(len(qs))
                    report["lessons_ok"] = int(report.get("lessons_ok") or 0) + 1
                else:
                    # Partial success policy: never fail the whole module regen because one lesson failed.
                    # Also: do NOT create an empty quiz. Keep the old quiz_id (if any) intact.
                    report["lessons_failed"] = int(report.get("lessons_failed") or 0) + 1
                    report["needs_regen"] = int(report.get("needs_regen") or 0) + 1
                    try:
                        provider_used = str(llm_debug.get("provider") or "").strip() or "unknown"
                        perr = str(llm_debug.get("provider_error") or "")
                        if provider_used == "unknown":
                            if perr.startswith("openrouter") or "openrouter" in perr:
                                provider_used = "openrouter"
                        reason = str(llm_debug.get("provider_error") or llm_debug.get("error") or "empty")
                        _persist_llm_debug(
                            entry={
                                "ts": datetime.utcnow().isoformat(),
                                "kind": "regen",
                                "module_id": str(m.id),
                                "submodule_id": str(sub.id),
                                "submodule_title": str(title),
                                "provider": provider_used,
                                "error": "lesson_failed_empty",
                                "provider_error": reason,
                                "questions_count": 0,
                            }
                        )
                    except Exception:
                        pass
                    _job_heartbeat(detail=f"FAIL {si_eff}/{int(effective_total)}: {title} · empty")
                    continue
            except Exception as e:
                # Per-lesson hard isolation: never abort entire module regen.
                try:
                    db.rollback()
                except Exception:
                    pass
                report["lessons_failed"] = int(report.get("lessons_failed") or 0) + 1
                report["needs_regen"] = int(report.get("needs_regen") or 0) + 1
                try:
                    _set_job_stage(stage="failed_lesson", detail=f"{si_eff}/{int(effective_total)}: {title}: {type(e).__name__}")
                    _job_heartbeat(detail=f"FAIL {si_eff}/{int(effective_total)}: {title} · {type(e).__name__}")
                except Exception:
                    pass
                continue

            try:
                db.flush()
            except Exception:
                pass
            try:
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass

            # Persist resume checkpoint AFTER commit (so we never mark a lesson done before it's durable).
            try:
                if sub_id_str:
                    done_ids.add(sub_id_str)
                ckpt = {
                    "module_id": str(m.id),
                    "module_title": str(getattr(m, "title", "") or ""),
                    "done_submodule_ids": list(done_ids)[-2000:],
                    "lessons_ok": int(report.get("lessons_ok") or 0),
                    "lessons_failed": int(report.get("lessons_failed") or 0),
                    "lessons_skipped": int(report.get("lessons_skipped") or 0),
                    "questions_total": int(report.get("questions_total") or 0),
                    "ts": datetime.utcnow().isoformat(),
                }
                _persist_regen_checkpoint(module_id=str(m.id), checkpoint=ckpt)
            except Exception:
                pass
            _job_heartbeat(detail=f"DONE {si_eff}/{int(effective_total)}: {title}")

            try:
                report.setdefault("lessons_meta", [])
                lessons_meta = report.get("lessons_meta")
                if isinstance(lessons_meta, list):
                    lessons_meta.append(
                    {
                        "submodule_id": str(sub.id),
                        "old_quiz_id": old_quiz_id,
                        "new_quiz_id": str(qid),
                        "old_questions": int(old_questions_count),
                        "new_questions": int(len(qs or []) or 1),
                        "ai_failed": bool(ai_failed),
                        "used_heuristic": bool(used_heuristic),
                    }
                    )
            except Exception:
                pass

        # Auto-publish only if there are no needs_regen:* questions left in DB for this module.
        # This is more reliable than using report counters (which may diverge from persisted data).
        # Important: questions are added to the session above; flush so COUNT() queries see them.
        try:
            db.flush()
        except Exception:
            pass

        needs_regen_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("needs_regen:%"))
        active_quiz_ids: list[uuid.UUID] = [sub.quiz_id for sub in (subs_all or []) if getattr(sub, "quiz_id", None)]
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

        try:
            modules_bump_rev(reason=f"regen:{str(m.id)}")
        except Exception:
            pass
        _set_job_stage(stage="done", detail=str(m.id))

        try:
            _clear_regen_checkpoint(module_id=str(m.id))
        except Exception:
            pass
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
