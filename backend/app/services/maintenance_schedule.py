"""Единое расписание фонового обслуживания хранилища.

Планировщик внутри API (`ENABLE_INPROCESS_SCHEDULER`), внешний cron и ручной
запуск обязаны делать одно и то же. Раньше было три разных набора: cron чистил
staging (отчёт), планировщик в API — только брошенные multipart-загрузки, а
`run-all` — вообще одну задачу. В любом варианте часть мусора оставалась:
незавершённые загрузки продолжали занимать место в S3 и оплачиваться.

Теперь набор задач описан здесь один раз, а вызывающие только решают, когда
его запустить.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from app.core.config import settings
from app.core.queue import get_queue
from app.core.redis_client import get_redis
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
    return results
