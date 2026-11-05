"""Ветка «индекс остался INVALID» в миграции 0029 — на подставном alembic.

Полупостроенный индекс (оборванный CONCURRENTLY) нельзя воспроизвести обычным
SQL: PostgreSQL не даёт пометить индекс невалидным без правки системного
каталога. Поэтому проверяем саму логику: если состояние `invalid`, миграция
обязана сначала удалить индекс, а потом создать заново — иначе `IF NOT EXISTS`
молча оставит битый индекс, и быстрые выборки тихо останутся медленными.
"""
from __future__ import annotations

import importlib.util
import pathlib
from contextlib import nullcontext


def _load_migration():
    path = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0029_hot_path_indexes.py"
    spec = importlib.util.spec_from_file_location("migration_0029", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _FakeOp:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def get_context(self):
        return type("Ctx", (), {"autocommit_block": staticmethod(nullcontext)})()

    def get_bind(self):
        return None

    def execute(self, statement) -> None:
        self.sql.append(str(statement))


def test_invalid_index_is_dropped_before_recreate():
    module = _load_migration()
    fake = _FakeOp()
    module.op = fake
    # Первый взгляд — битый индекс, после DROP он уже отсутствует.
    states = iter(["invalid", "missing"])
    module._index_state = lambda name: next(states)  # type: ignore[assignment]

    module._ensure_index("ix_quiz_attempts_user_started_at", "quiz_attempts", "user_id, started_at")

    assert fake.sql[0] == "DROP INDEX CONCURRENTLY IF EXISTS ix_quiz_attempts_user_started_at"
    assert fake.sql[1].startswith("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_quiz_attempts_user_started_at")


def test_valid_index_is_left_alone():
    module = _load_migration()
    fake = _FakeOp()
    module.op = fake
    module._index_state = lambda name: "valid"  # type: ignore[assignment]

    module._ensure_index("ix_learning_events_created_at", "learning_events", "created_at")

    assert fake.sql == []
