"""Предел размера ZIP-архива модуля.

Лимит материалов (`upload_max_bytes`, задаётся в интерфейсе) относится к файлам,
видео и материалам продаж. Архив модуля — отдельная история: его скачивает и
распаковывает воркер, поэтому у него собственный потолок.

Одно значение на все входы: предподписанная загрузка, multipart, повторный
импорт через сервер и сам воркер. Предел задаётся в «Админ-центр → Настройки»
(значение из `IMPORT_ZIP_MAX_ARCHIVE_BYTES` — только начальное), поэтому
изменение в интерфейсе действует во всех путях без перезапуска.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings

DEFAULT_ARCHIVE_MAX_BYTES = 1024 ** 3


def _from_env() -> int:
    value = int(getattr(settings, "import_zip_max_archive_bytes", DEFAULT_ARCHIVE_MAX_BYTES) or 0)
    return value if value > 0 else DEFAULT_ARCHIVE_MAX_BYTES


def archive_max_bytes(db: Session | None = None) -> int:
    """Действующий предел архива: значение из БД, иначе — из окружения.

    База недоступна (воркер без БД, ранний старт) — честно откатываемся на env,
    чтобы импорт не падал из-за проверки размера.
    """

    if db is not None:
        from app.services.app_settings import get_platform_settings

        try:
            value = int(get_platform_settings(db).zip_max_archive_bytes or 0)
        except Exception:
            return _from_env()
        return value if value > 0 else _from_env()

    from app.db.session import SessionLocal

    try:
        with SessionLocal() as own:
            return archive_max_bytes(own)
    except Exception:
        return _from_env()


def archive_limit_human(db: Session | None = None) -> str:
    size = archive_max_bytes(db)
    if size >= 1024 ** 3 and size % (1024 ** 3) == 0:
        return f"{size // (1024 ** 3)} ГБ"
    return f"{size // (1024 * 1024)} МБ"


def too_large_message(size_bytes: int | None = None, db: Session | None = None) -> str:
    return f"ZIP-архив больше предела {archive_limit_human(db)}. Предел задаётся в «Админ-центр → Настройки»."
