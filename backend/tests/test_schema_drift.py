"""Модели и миграции не должны расходиться.

Расхождение — мина замедленного действия: код уже обращается к колонке, а на
проде миграция её не создала (или наоборот, autogenerate предлагает удалить
рабочий индекс). Тест поднимает пустую базу миграциями до `head` и сравнивает
её со `Base.metadata`.

Осознанно допускается ровно одно отличие: `ix_users_email_ci` — частичный
функциональный уникальный индекс `lower(email)` из миграции 0016. SQLAlchemy
не умеет описывать такие индексы в метаданных, поэтому в модели его нет;
обычный unique-индекс не ловил бы `Ivan@…` и `ivan@…` как один адрес.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import pkgutil

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

MIGRATION_URL = os.getenv("TEST_MIGRATION_DATABASE_URL")
ALLOWED_INDEXES = {"ix_users_email_ci"}
IGNORED_KINDS = {"modify_default", "modify_comment"}


def _load_models() -> None:
    import app.models as models_package

    for module in pkgutil.iter_modules(models_package.__path__):
        importlib.import_module(f"app.models.{module.name}")


def _describe(diff) -> str:
    return str(diff)[:200]


def _flatten(items):
    """Alembic возвращает вложенные списки, когда у одного объекта несколько правок."""
    for item in items:
        if isinstance(item, list):
            yield from _flatten(item)
        else:
            yield item


@pytest.mark.skipif(not MIGRATION_URL, reason="requires disposable PostgreSQL migration database")
def test_metadata_matches_migrations(monkeypatch):
    from app.core.config import settings

    url = MIGRATION_URL
    assert url
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    monkeypatch.setattr(settings, "database_url", url)
    root = pathlib.Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")

    _load_models()
    from app.db.base import Base

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    unexpected = []
    for diff in _flatten(differences):
        kind = diff[0] if isinstance(diff, tuple) else ""
        if kind in IGNORED_KINDS:
            # Python-значения по умолчанию (`default=...`) Alembic показывает как
            # «серверные»: в базе их нет, но приложение всегда пишет значение само.
            continue
        if kind == "remove_index" and getattr(diff[1], "name", "") in ALLOWED_INDEXES:
            continue
        unexpected.append(_describe(diff))

    assert not unexpected, (
        "схема БД и модели разошлись — нужна миграция (или правка модели):\n" + "\n".join(unexpected)
    )
