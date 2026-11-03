"""Предел размера ZIP-архива модуля.

Лимит материалов (`upload_max_bytes`, задаётся в интерфейсе) относится к файлам,
видео и материалам продаж. Архив модуля — отдельная история: его скачивает и
распаковывает воркер, поэтому у него собственный потолок
(`IMPORT_ZIP_MAX_ARCHIVE_BYTES`, по умолчанию 1 ГБ).

Одно значение на все входы: предподписанная загрузка, multipart, повторный
импорт через сервер и сам воркер. Раньше предел был только у повторного импорта
(жёстко 1 ГБ), а прямой путь импорта не проверял размер вовсе.
"""

from __future__ import annotations

from app.core.config import settings

DEFAULT_ARCHIVE_MAX_BYTES = 1024 ** 3


def archive_max_bytes() -> int:
    value = int(getattr(settings, "import_zip_max_archive_bytes", DEFAULT_ARCHIVE_MAX_BYTES) or 0)
    return value if value > 0 else DEFAULT_ARCHIVE_MAX_BYTES


def archive_limit_human() -> str:
    size = archive_max_bytes()
    if size >= 1024 ** 3 and size % (1024 ** 3) == 0:
        return f"{size // (1024 ** 3)} ГБ"
    return f"{size // (1024 * 1024)} МБ"


def too_large_message(size_bytes: int | None = None) -> str:
    prefix = "ZIP-архив больше предела" if size_bytes else "ZIP-архив больше предела"
    return f"{prefix} {archive_limit_human()}. Предел задаётся IMPORT_ZIP_MAX_ARCHIVE_BYTES."
