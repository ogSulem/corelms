"""Подключение к PostgreSQL.

Пул намеренно ограничен: на VPS с 2 ГБ памяти пять контейнеров не должны
исчерпать `max_connections` у Postgres. Когда соединения заканчиваются,
SQLAlchemy бросает `TimeoutError`, и без явной настройки это выглядит как
обычная «Ошибка сервера» — поэтому таймаут короткий, а наружу отдаётся 503
(см. обработчик в app/main.py).
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


# 5 постоянных + 10 временных соединений на процесс. С одним uvicorn-воркером
# это максимум 15, что оставляет запас остальным контейнерам.
POOL_SIZE = _int_env("DB_POOL_SIZE", 5)
MAX_OVERFLOW = _int_env("DB_MAX_OVERFLOW", 10)
POOL_TIMEOUT = _int_env("DB_POOL_TIMEOUT_SECONDS", 20)
POOL_RECYCLE = _int_env("DB_POOL_RECYCLE_SECONDS", 1800)

_url = str(settings.database_url or "")

# SQLite (тесты) использует SingletonThreadPool и не принимает параметры размера пула.
_pool_kwargs: dict[str, int] = {}
if _url.startswith("postgresql"):
    _pool_kwargs = {
        "pool_size": POOL_SIZE,
        "max_overflow": MAX_OVERFLOW,
        "pool_timeout": POOL_TIMEOUT,
        "pool_recycle": POOL_RECYCLE,
    }

engine = create_engine(_url, pool_pre_ping=True, **_pool_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def pool_snapshot() -> dict[str, int | str]:
    """Состояние пула для диагностики: видно, не заняты ли все соединения."""
    pool = engine.pool
    name = type(pool).__name__

    def _call(attr: str) -> int | None:
        fn = getattr(pool, attr, None)
        if not callable(fn):
            return None
        try:
            return int(fn())
        except Exception:
            return None

    size = _call("size")
    checked_out = _call("checkedout")
    return {
        "pool": name,
        "size": size if size is not None else 0,
        "checked_in": _call("checkedin") or 0,
        "checked_out": checked_out or 0,
        "overflow": _call("overflow") or 0,
        "max_overflow": MAX_OVERFLOW if name == "QueuePool" else 0,
        "timeout_seconds": POOL_TIMEOUT if name == "QueuePool" else 0,
    }
