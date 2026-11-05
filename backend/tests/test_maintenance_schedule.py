"""Расписание обслуживания хранилища: один набор задач для всех путей запуска.

Раньше cron чистил staging, а планировщик внутри API — только брошенные
multipart-загрузки. Любой вариант оставлял часть мусора в S3, поэтому набор
задач живёт в одном месте и проверяется здесь.
"""

from __future__ import annotations

import pytest

from app.services import maintenance_schedule


class _FakeRedis:
    def __init__(self) -> None:
        self.keys: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):  # noqa: A002
        if nx and key in self.keys:
            return None
        self.keys[key] = str(value)
        return True


class _Job:
    def __init__(self, name: str) -> None:
        self.id = f"job-{name}"


class _FakeQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_on: set[str] = set()

    def enqueue(self, fn, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        if name in self.fail_on:
            raise RuntimeError("queue is down")
        self.calls.append((name, kwargs))
        return _Job(name)


@pytest.fixture()
def maintenance(monkeypatch):
    redis = _FakeRedis()
    queue = _FakeQueue()
    monkeypatch.setattr(maintenance_schedule, "get_redis", lambda: redis)
    monkeypatch.setattr(maintenance_schedule, "get_queue", lambda name: queue)
    return redis, queue


def test_every_run_covers_uploads_and_multipart(maintenance):
    """Стоки и брошенные multipart-загрузки чистятся одним и тем же запуском."""
    _redis, queue = maintenance
    result = maintenance_schedule.run_due_tasks()

    assert result["ok"] is True
    names = [name for name, _kwargs in queue.calls]
    assert names == ["cleanup_admin_uploads_job", "cleanup_admin_multipart_uploads_job"], names
    multipart_kwargs = dict(queue.calls)["cleanup_admin_multipart_uploads_job"]
    # Префикс покрывает и uploads/sources/…zip, и uploads/admin/…: раньше
    # cron проверял только uploads/admin/, а планировщик — uploads/.
    assert multipart_kwargs["prefix"] == "uploads/"
    assert set(result["tasks"]) == {"admin_uploads_cleanup", "admin_multipart_cleanup"}


def test_second_run_does_not_duplicate_work(maintenance):
    """Блокировка в Redis: несколько инстансов не плодят одинаковые задачи."""
    _redis, queue = maintenance
    maintenance_schedule.run_due_tasks()
    first = len(queue.calls)
    second = maintenance_schedule.run_due_tasks()

    assert len(queue.calls) == first
    assert all(task.get("enqueued") is False for task in second["tasks"].values())


def test_one_broken_task_does_not_stop_the_other(maintenance):
    """Если очередь отклонила отчёт, multipart-очистка всё равно должна пройти."""
    _redis, queue = maintenance
    queue.fail_on = {"cleanup_admin_uploads_job"}
    result = maintenance_schedule.run_due_tasks()

    assert result["tasks"]["admin_uploads_cleanup"]["ok"] is False
    assert result["tasks"]["admin_multipart_cleanup"]["ok"] is True
    assert [name for name, _ in queue.calls] == ["cleanup_admin_multipart_uploads_job"]


def test_redis_outage_is_reported_not_raised(monkeypatch):
    def boom():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(maintenance_schedule, "get_redis", boom)
    result = maintenance_schedule.run_due_tasks()

    assert result["ok"] is False
    assert "redis is down" in result["error"]


def test_lock_expires_before_the_next_tick(maintenance):
    """Блокировка снимается раньше следующего тика, иначе задачи встанут навсегда."""
    from app.core.config import settings

    interval = maintenance_schedule.interval_seconds()
    assert interval >= 60
    for task in maintenance_schedule.tasks():
        assert task.lock_ttl < interval, task.name
        assert task.lock_ttl >= 60, task.name
    assert int(settings.uploads_admin_cleanup_interval_minutes) >= 1


def test_uploads_report_covers_the_whole_staging_prefix(maintenance):
    """Отчёт должен смотреть весь staging, а не только `uploads/admin/`.

    Брошенные загрузки администратора лежат в `uploads/sources/…zip`, поэтому
    прежний отчёт по `uploads/admin/` всегда был пустым — задача выглядела
    работающей, но не проверяла ничего.
    """

    _redis, queue = maintenance
    maintenance_schedule.run_due_tasks()
    kwargs = dict(queue.calls)["cleanup_admin_uploads_job"]
    assert kwargs["prefix"] == "uploads/"
    assert maintenance_schedule.UPLOADS_PREFIX == "uploads/"
