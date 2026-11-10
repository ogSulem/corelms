"""Порядок шагов деплоя — часть гарантии «данные не теряются».

`deploy/update.sh` запускают одной командой, поэтому копия базы должна делаться
внутри скрипта, а не только в инструкции. Здесь зафиксировано:

* копия вызывается ДО миграций (откат образов не отменяет миграцию);
* копия вызывается ДО пересборки образов (иначе её можно не дождаться);
* отказ копии останавливает обновление;
* осознанный обход (`SKIP_BACKUP=1`) предусмотрен и не молчит.

Тест читает сам скрипт: это дешёвая страховка от случайного удаления шага при
следующей правке деплоя.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPDATE = ROOT / "deploy" / "update.sh"
BACKUP = ROOT / "scripts" / "backup.sh"


def _script() -> str:
    return UPDATE.read_text(encoding="utf-8")


def test_backup_script_exists():
    assert BACKUP.is_file(), "без scripts/backup.sh update.sh не сможет сделать копию"


def test_backup_runs_before_images_are_rebuilt_and_migrated():
    text = _script()
    backup_at = text.find("scripts/backup.sh")
    build_at = text.find("bash deploy/rebuild-offline.sh")
    migrate_at = text.find("alembic backend upgrade head")
    assert backup_at != -1, "в update.sh нет шага резервной копии"
    assert build_at != -1 and migrate_at != -1
    assert backup_at < build_at, "копия должна делаться до пересборки образов"
    assert backup_at < migrate_at, "копия должна делаться до миграций"


def test_failed_backup_stops_the_update():
    text = _script()
    # Условие «копия не создана» обязано завершать скрипт, а не продолжаться.
    guards = [line.strip() for line in text.splitlines() if "Резервная копия не создана" in line]
    assert guards, "нет обработки неудачной копии"
    assert any(line.startswith("die ") for line in guards), "ошибка копии должна останавливать обновление"


def test_backup_can_be_skipped_explicitly():
    text = _script()
    assert "SKIP_BACKUP" in text
    assert "SKIP_BACKUP=1" in text


def test_postgres_readiness_failure_is_loud():
    """На неготовой базе миграции не запускаются «молча»."""
    text = _script()
    assert "pg_ready=1" in text
    assert 'die "PostgreSQL не ответил' in text


def test_backup_is_only_run_when_database_container_is_up():
    """Первая установка запускает update.sh без работающего postgres."""
    text = _script()
    assert 'grep -qx "postgres"' in text
