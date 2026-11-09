"""Единое расписание фонового обслуживания хранилища.

Планировщик внутри API (`ENABLE_INPROCESS_SCHEDULER`), внешний cron и ручной
запуск обязаны делать одно и то же. Раньше было три разных набора: cron чистил
staging (отчёт), планировщик в API — только брошенные multipart-загрузки, а
`run-all` — вообще одну задачу. В любом варианте часть мусора оставалась:
незавершённые загрузки продолжали занимать место в S3 и оплачиваться.

Теперь набор задач описан здесь один раз, а вызывающие только решают, когда
его запустить.

Кроме задач очереди есть местные (`local_tasks`): они работают с диском того
контейнера, где живёт планировщик, — промежуточные части докачки лежат на
томе `backend_data`, который смонтирован только в backend. Отправить такую
задачу в worker означало бы «успешно» убирать чужую пустую папку.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from app.core.config import settings
from app.core.queue import get_queue
from app.core.redis_client import get_redis
from app.db.session import SessionLocal
from app.services.chunked_uploads import sweep_stale as sweep_upload_staging
from app.services.password_reset import purge_stale as purge_stale_reset_tokens
from app.services.storage_cleanup_jobs import cleanup_admin_multipart_uploads_job, cleanup_admin_uploads_job

log = logging.getLogger(__name__)

# Все загрузки администратора лежат под этим префиксом: `uploads/sources/…zip`
# (импорт), `uploads/admin/…` (файлы), исторические ключи в корне `uploads/`.
UPLOADS_PREFIX = "uploads/"


@dataclass(frozen=True)
class MaintenanceTask:
    name: str
    lock: str
    lock_ttl: int
    enqueue: Callable[[Any], Any]


@dataclass(frozen=True)
class LocalTask:
    """Задача, которая выполняется в процессе API, а не в очереди."""

    name: str
    lock: str
    lock_ttl: int
    run: Callable[[], dict[str, Any]]


def interval_seconds() -> int:
    return max(60, int(getattr(settings, "uploads_admin_cleanup_interval_minutes", 15) or 15) * 60)


def tasks() -> list[MaintenanceTask]:
    """Периодические задачи обслуживания. Порядок — от безопасного к строгому."""
    ttl_seconds = max(60, interval_seconds() - 5)
    return [
        MaintenanceTask(
            name="admin_uploads_cleanup",
            lock="locks:admin_uploads_cleanup",
            lock_ttl=ttl_seconds,
            # Только отчёт: физическое удаление требует бэкапа и остановки записи.
            enqueue=lambda q: q.enqueue(
                cleanup_admin_uploads_job,
                # Отчёт по всему staging: `uploads/sources/` (архивы импорта) и
                # `uploads/admin/` (файлы). Раньше отчёт смотрел только второй
                # префикс, где брошенных загрузок не появляется.
                prefix=UPLOADS_PREFIX,
                ttl_hours=int(getattr(settings, "uploads_admin_ttl_hours", 6) or 6),
                job_timeout=60 * 10,
                result_ttl=60 * 60,
                failure_ttl=60 * 60,
            ),
        ),
        MaintenanceTask(
            name="admin_multipart_cleanup",
            lock="locks:admin_multipart_cleanup",
            lock_ttl=ttl_seconds,
            # Брошенные multipart-загрузки не содержат готовых файлов — их можно
            # прерывать безопасно; иначе они копятся в S3 навсегда.
            enqueue=lambda q: q.enqueue(
                cleanup_admin_multipart_uploads_job,
                prefix=UPLOADS_PREFIX,
                ttl_hours=int(getattr(settings, "uploads_admin_multipart_ttl_hours", 12) or 12),
                job_timeout=60 * 10,
                result_ttl=60 * 60,
                failure_ttl=60 * 60,
            ),
        ),
    ]


def sweep_local_junk() -> dict[str, Any]:
    """Убрать то, что лежит рядом с API и растёт без активности пользователей.

    Шаги независимы: сбой одного не мешает другому, а ошибка попадает в отчёт.
    """
    result: dict[str, Any] = {"ok": True}
    try:
        result["removed_upload_sessions"] = int(sweep_upload_staging() or 0)
    except Exception as exc:
        result["ok"] = False
        result["upload_sessions_error"] = f"{type(exc).__name__}: {exc}"[:200]
        log.warning("maintenance: уборка сессий докачки не удалась: %s", exc)
    try:
        with SessionLocal() as db:
            result["removed_reset_tokens"] = int(purge_stale_reset_tokens(db))
            db.commit()
    except Exception as exc:
        result["ok"] = False
        result["reset_tokens_error"] = f"{type(exc).__name__}: {exc}"[:200]
        log.warning("maintenance: уборка старых ссылок сброса пароля не удалась: %s", exc)
    return result


def local_tasks() -> list[LocalTask]:
    """Местные уборки: тот же интервал и та же защита от дублей, что у очереди."""
    ttl_seconds = max(60, interval_seconds() - 5)
    return [
        LocalTask(
            name="local_junk_sweep",
            lock="locks:local_junk_sweep",
            lock_ttl=ttl_seconds,
            run=sweep_local_junk,
        ),
    ]


def run_due_tasks() -> dict[str, Any]:
    """Поставить задачи в очередь, если их не поставил другой инстанс.

    Блокировка в Redis на каждую задачу: несколько API-контейнеров и внешний
    cron не создают дубли, а падение процесса освобождает её по TTL.
    """
    results: dict[str, Any] = {"ok": True, "tasks": {}}
    try:
        redis = get_redis()
    except Exception as exc:  # Redis недоступен — задачи ставить некуда
        return {"ok": False, "tasks": {}, "error": f"{type(exc).__name__}: {exc}"[:200]}

    for task in tasks():
        try:
            acquired = redis.set(task.lock, "1", nx=True, ex=int(task.lock_ttl))
            if not acquired:
                results["tasks"][task.name] = {"ok": True, "enqueued": False, "reason": "locked"}
                continue
            job = task.enqueue(get_queue(str(settings.rq_queue_cleanup)))
            results["tasks"][task.name] = {"ok": True, "enqueued": True, "job_id": str(getattr(job, "id", ""))}
        except Exception as exc:
            results["tasks"][task.name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
            log.warning("maintenance: %s не поставлена в очередь: %s", task.name, exc)

    for local in local_tasks():
        try:
            acquired = redis.set(local.lock, "1", nx=True, ex=int(local.lock_ttl))
            if not acquired:
                results["tasks"][local.name] = {"ok": True, "ran": False, "reason": "locked"}
                continue
            results["tasks"][local.name] = {"ran": True, **local.run()}
        except Exception as exc:
            results["tasks"][local.name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
            log.warning("maintenance: %s не выполнена: %s", local.name, exc)
    return results
