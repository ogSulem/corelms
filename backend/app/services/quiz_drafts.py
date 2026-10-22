"""Bounded module-wide AI draft preparation; never changes a published quiz.

RQ jobs, latest-lesson pointers and the batch receipt are delivered in one Redis
transaction. A lost enqueue response is recoverable without duplicate AI calls.
"""
from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timezone

from fastapi import HTTPException
from rq.job import Job
from sqlalchemy import func, select

from app.core.config import settings
from app.core.queue import get_queue, get_job_status
from app.core.redis_client import get_redis
from app.models.module import Module, Submodule
from app.models.quiz import Question
from app.services.authoring import generate_quiz_draft_job, request_signature, source_revision

TTL = 7 * 86400
RUNNING = {"queued", "started", "scheduled", "deferred"}
MAX_LESSONS = 50


def draft_key(module_id, lesson_id):
    return f"authoring:draft:{module_id}:{lesson_id}"


def batch_key(module_id, batch_id=None):
    return f"authoring:batch:{module_id}:{batch_id or 'latest'}"


def _text(value):
    return value.decode() if isinstance(value, bytes) else str(value)


def prepare_module_drafts(db, module: Module, *, actor_id, count: int, only_missing: bool, lesson_ids=None) -> dict:
    if not str(settings.openrouter_api_key or "").strip():
        raise HTTPException(503, "AI-провайдер не настроен. Материалы сохранены; тесты можно создать вручную или настроить OPENROUTER_API_KEY.")
    all_lessons = list(db.scalars(select(Submodule).where(Submodule.module_id == module.id,
        Submodule.is_archived.is_(False), Submodule.is_folder.is_(False)).order_by(Submodule.order, Submodule.id)))
    if lesson_ids is not None:
        wanted = set(lesson_ids)
        if not wanted.issubset({lesson.id for lesson in all_lessons}):
            raise HTTPException(422, "Выберите активные уроки только этого модуля")
        all_lessons = [lesson for lesson in all_lessons if lesson.id in wanted]
    question_counts = dict(db.execute(select(Question.quiz_id, func.count()).where(
        Question.quiz_id.in_([lesson.quiz_id for lesson in all_lessons])).group_by(Question.quiz_id)).all())
    selected = [lesson for lesson in all_lessons if not only_missing or not question_counts.get(lesson.quiz_id)]
    if not selected:
        return {"id": None, "items": [], "working": False, "counts": {}, "remaining": 0,
                "message": "Во всех выбранных уроках уже есть вопросы." if all_lessons else "Сначала добавьте учебные уроки. Каталоги файлов не требуют тестов."}
    # Prefer unprepared lessons in order; valid existing drafts are returned, not charged again.
    queue = get_queue(settings.rq_queue_regen)
    redis = queue.connection  # RQ data is binary; never deserialize it with decode_responses=True.
    selected = selected[:MAX_LESSONS]
    fingerprints = {lesson.id: source_revision(db, lesson) for lesson in selected}
    try:
        old_ids = redis.mget([draft_key(module.id, lesson.id) for lesson in selected])
        existing_ids = [_text(value) for value in old_ids if value]
        existing = {job.id: job for job in Job.fetch_many(existing_ids, connection=redis) if job}
        jobs, items = [], []
        for lesson, old_id in zip(selected, old_ids):
            fingerprint = fingerprints[lesson.id]
            signature = request_signature(fingerprint, count)
            old = existing.get(_text(old_id)) if old_id else None
            valid = bool(old and (old.meta or {}).get("job_kind") == "quiz_draft"
                         and (old.meta or {}).get("module_id") == str(module.id)
                         and (old.meta or {}).get("lesson_id") == str(lesson.id)
                         and (old.meta or {}).get("request_signature") == signature)
            status = get_job_status(old, refresh=False) if valid else None
            reuse = valid and (status in RUNNING or (status == "finished" and isinstance(old.result, dict) and old.result.get("ok")))
            job_id = old.id if reuse else uuid.uuid4().hex
            if not reuse:
                jobs.append(queue.prepare_data(generate_quiz_draft_job,
                    args=(str(module.id), str(lesson.id), module.content_revision, count, None),
                    kwargs={"source_fingerprint": fingerprint}, job_id=job_id, timeout=300,
                    result_ttl=TTL, failure_ttl=TTL,
                    meta={"job_kind": "quiz_draft", "module_id": str(module.id), "lesson_id": str(lesson.id),
                          "actor_user_id": str(actor_id), "revision": module.content_revision,
                          "source_revision": fingerprint, "request_signature": signature}))
            items.append({"lesson_id": str(lesson.id), "title": lesson.title, "job_id": job_id,
                          "source_revision": fingerprint, "reused": bool(reuse)})
        receipt = {"id": uuid.uuid4().hex, "module_id": str(module.id), "items": items,
                   "created_at": datetime.now(timezone.utc).isoformat(),
                   "remaining": max(0, len([lesson for lesson in all_lessons if not only_missing or not question_counts.get(lesson.quiz_id)]) - len(selected))}
        with redis.pipeline(transaction=True) as pipeline:
            if jobs:
                queue.enqueue_many(jobs, pipeline=pipeline)
            for item in items:
                pipeline.setex(draft_key(module.id, item["lesson_id"]), TTL, item["job_id"])
            pipeline.setex(batch_key(module.id, receipt["id"]), TTL, json.dumps(receipt, ensure_ascii=False))
            pipeline.setex(batch_key(module.id), TTL, receipt["id"])
            pipeline.execute()
        return receipt
    except Exception as exc:
        raise HTTPException(503, "Запуск AI не подтверждён. Материалы и действующие тесты не изменены. Обновите статус перед повтором.") from exc


def module_draft_status(db, module: Module, batch_id: str | None = None) -> dict:
    try:
        redis = get_redis()
        if not batch_id:
            raw_id = redis.get(batch_key(module.id))
            batch_id = _text(raw_id) if raw_id else None
        if not batch_id:
            return {"id": None, "items": [], "working": False, "counts": {}, "remaining": 0}
        # Explicitly scope the stored receipt, not a caller-supplied global RQ ID.
        batch_id = uuid.UUID(batch_id).hex
        raw = redis.get(batch_key(module.id, batch_id))
        if not raw:
            return {"id": batch_id, "items": [], "working": False, "counts": {}, "remaining": 0,
                    "message": "Отчёт больше не хранится (срок — 7 дней). Можно запустить подготовку снова."}
        receipt = json.loads(raw)
        if receipt.get("module_id") != str(module.id):
            raise ValueError("invalid batch scope")
        items = receipt["items"][:MAX_LESSONS]
        queue = get_queue(settings.rq_queue_regen)
        jobs = {job.id: job for job in Job.fetch_many([item["job_id"] for item in items], connection=queue.connection) if job}
        lessons = {str(lesson.id): lesson for lesson in db.scalars(select(Submodule).where(
            Submodule.module_id == module.id, Submodule.id.in_([uuid.UUID(item["lesson_id"]) for item in items])))}
        question_counts = dict(db.execute(select(Question.quiz_id, func.count()).where(
            Question.quiz_id.in_([lesson.quiz_id for lesson in lessons.values()])).group_by(Question.quiz_id)).all())
        output, working = [], False
        for item in items:
            job = jobs.get(item["job_id"])
            lesson = lessons.get(item["lesson_id"])
            status = get_job_status(job, refresh=False) if job else "missing"
            working = working or status in RUNNING
            stale = not lesson or module.is_archived or lesson.is_archived or lesson.is_folder or source_revision(db, lesson) != item["source_revision"]
            if job and ((job.meta or {}).get("module_id") != str(module.id) or (job.meta or {}).get("lesson_id") != item["lesson_id"]):
                raise ValueError("invalid job scope")
            result = job.result if job and status == "finished" else None
            current_questions = question_counts.get(lesson.quiz_id, 0) if lesson else 0
            state = "stale" if stale else "configured" if current_questions else "ready" if result and result.get("ok") else "needs_source" if result and result.get("error_code") == "insufficient_source" else "failed" if status in {"failed", "stopped", "canceled", "missing", "finished"} else status
            output.append({"lesson_id": item["lesson_id"], "title": lesson.title if lesson else item["title"],
                "status": state, "questions": len(result.get("questions") or []) if result and result.get("ok") else 0,
                "current_questions": current_questions, "required": bool(lesson and lesson.requires_quiz),
                "error": result.get("error") if isinstance(result, dict) else "Обработчик прервался; действующий тест не изменён." if state == "failed" else None})
        return {"id": batch_id, "items": output, "working": working, "counts": dict(Counter(item["status"] for item in output)),
                "remaining": receipt.get("remaining", 0)}
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(404, "Отчёт подготовки этого модуля не найден") from exc
    except Exception as exc:
        raise HTTPException(503, "Не удалось получить статус AI. Дождитесь восстановления связи; черновики не удалены.") from exc
