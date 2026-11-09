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
    # Местная уборка ходит на диск и в базу: в этих тестах она подменена,
    # иначе проверка расписания зависела бы от содержимого /data.
    monkeypatch.setattr(maintenance_schedule, "sweep_upload_staging", lambda: 0)
    monkeypatch.setattr(maintenance_schedule, "purge_stale_reset_tokens", lambda db: 0)
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
    assert set(result["tasks"]) == {
        "admin_uploads_cleanup",
        "admin_multipart_cleanup",
        "local_junk_sweep",
    }


def test_second_run_does_not_duplicate_work(maintenance):
    """Блокировка в Redis: несколько инстансов не плодят одинаковые задачи."""
    _redis, queue = maintenance
    maintenance_schedule.run_due_tasks()
    first = len(queue.calls)
    second = maintenance_schedule.run_due_tasks()

    assert len(queue.calls) == first
    assert all(task.get("enqueued") is not True for task in second["tasks"].values())
    assert all(task.get("ran") is not True for task in second["tasks"].values())


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
    for task in [*maintenance_schedule.tasks(), *maintenance_schedule.local_tasks()]:
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


def test_local_sweep_removes_stale_upload_sessions_and_old_reset_tokens(
    monkeypatch, tmp_path, db, make_user, redis_memory
):
    """Мусор рядом с API убирается сам, даже если users месяцами ничего не делают.

    Раньше брошенные сессии докачки подметались только при старте новой загрузки,
    а просроченные ссылки сброса пароля — только при выпуске новой ссылки.
    На установке без активности оба вида записей оставались навсегда.
    """
    import os
    import time as _time
    from datetime import datetime, timedelta, timezone

    from app.core.config import settings
    from app.models.password_reset import PasswordResetToken

    staging = tmp_path / "staging"
    staging.mkdir()
    stale_id, fresh_id = "a" * 32, "b" * 32
    for name, age_hours in ((stale_id, 48), (fresh_id, 1)):
        directory = staging / name
        directory.mkdir()
        (directory / "meta.json").write_text("{}", encoding="utf-8")
        stamp = _time.time() - age_hours * 3600
        os.utime(directory, (stamp, stamp))

    monkeypatch.setattr(settings, "upload_staging_dir", str(staging))
    monkeypatch.setattr(settings, "upload_session_ttl_hours", 24)

    user, _headers = make_user()
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            PasswordResetToken(
                user_id=user.id,
                token_hash="stale" * 10,
                expires_at=now - timedelta(days=40),
                created_at=now - timedelta(days=41),
            ),
            PasswordResetToken(
                user_id=user.id,
                token_hash="fresh" * 10,
                expires_at=now + timedelta(hours=5),
                created_at=now - timedelta(days=41),
            ),
        ]
    )
    db.commit()

    queue = _FakeQueue()
    monkeypatch.setattr(maintenance_schedule, "get_queue", lambda name: queue)
    result = maintenance_schedule.run_due_tasks()

    sweep = result["tasks"]["local_junk_sweep"]
    assert sweep["ok"] is True, sweep
    assert sweep["removed_upload_sessions"] == 1, sweep
    assert not (staging / stale_id).exists()
    assert (staging / fresh_id).exists()

    # Просроченная запись убрана, действующая ссылка (та же давняя выдача) — нет.
    assert sweep["removed_reset_tokens"] == 1, sweep
    left = db.query(PasswordResetToken).all()
    assert [row.token_hash[:5] for row in left] == ["fresh"]


def test_local_sweep_failure_is_reported_and_does_not_block_the_queue(
    maintenance, monkeypatch
):
    """Если диск недоступен, задачи очереди всё равно ставятся."""
    _redis, queue = maintenance

    def boom() -> int:
        raise PermissionError("staging is read-only")

    monkeypatch.setattr(maintenance_schedule, "sweep_upload_staging", boom)
    result = maintenance_schedule.run_due_tasks()

    assert result["tasks"]["local_junk_sweep"]["ok"] is False
    assert "read-only" in result["tasks"]["local_junk_sweep"]["upload_sessions_error"]
    assert [name for name, _ in queue.calls] == [
        "cleanup_admin_uploads_job",
        "cleanup_admin_multipart_uploads_job",
    ]
