"""Журнал ошибок приложения, доступный администратору без SSH.

Сервер отвечает 500 без деталей (это правильно для безопасности), поэтому
причину раньше можно было увидеть только в `docker compose logs`. Здесь
ошибки складываются в файл на томе `backend_data` и отдаются администратору
через `/admin/diagnostics/errors`.

Файл не растёт бесконечно: при превышении лимита он переименовывается в
`errors.jsonl.1` (предыдущая версия перезаписывается).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
import traceback as tb_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024 * 1024
LOCK = threading.Lock()

# Коды уже записанных запросов: обработчик исключения и middleware могут
# увидеть одну и ту же ошибку, а дублировать её в журнале не нужно.
RECORDED: deque[str] = deque(maxlen=200)

# Сколько символов traceback хранить: достаточно, чтобы увидеть место падения.
MAX_TRACEBACK_CHARS = 6000
MAX_MESSAGE_CHARS = 600


def log_path() -> Path:
    raw = str(os.getenv("CORELMS_ERROR_LOG_PATH") or "").strip()
    if raw:
        return Path(raw)
    return Path("/data/logs/errors.jsonl")


def _fallback_path() -> Path:
    return Path("/tmp/corelms-errors.jsonl")


def _read_candidates() -> list[Path]:
    # Явно заданный путь (переменная окружения) — единственный источник правды.
    if str(os.getenv("CORELMS_ERROR_LOG_PATH") or "").strip():
        return [log_path()]
    return [log_path(), _fallback_path()]


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except Exception:
        log.debug("error log rotation failed", exc_info=True)


def record(
    *,
    rid: str,
    method: str,
    path: str,
    status: int,
    user_id: str | None = None,
    duration_ms: int | None = None,
    exc: BaseException | None = None,
) -> None:
    """Записать ошибку. Никогда не бросает исключение наружу."""
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rid": str(rid or ""),
        "method": str(method or ""),
        "path": str(path or ""),
        "status": int(status or 500),
        "user_id": str(user_id) if user_id else None,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
    }
    if exc is not None:
        entry["error"] = f"{type(exc).__name__}: {exc}"[:MAX_MESSAGE_CHARS]
        entry["traceback"] = "".join(
            tb_module.format_exception(type(exc), exc, exc.__traceback__)
        )[-MAX_TRACEBACK_CHARS:]
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    if entry["rid"]:
        RECORDED.append(entry["rid"])

    for candidate in (log_path(), _fallback_path()):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            with LOCK:
                _rotate(candidate)
                with candidate.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            return
        except Exception:
            log.debug("error log write failed for %s", candidate, exc_info=True)


def has_recorded(rid: str) -> bool:
    return bool(rid) and str(rid) in RECORDED


def _parse(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def read_recent(limit: int = 50, *, rid: str | None = None) -> tuple[list[dict[str, Any]], Path | None]:
    """Вернуть последние ошибки (сначала свежие) и путь к файлу журнала."""
    take = max(1, min(int(limit or 50), 200))
    for candidate in _read_candidates():
        if not candidate.exists():
            continue
        try:
            # Читаем хвост файла целиком: он ограничен 2 МБ.
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        items: list[dict[str, Any]] = []
        seen: dict[str, int] = {}
        for line in reversed(lines):
            entry = _parse(line)
            if not entry:
                continue
            if rid and str(entry.get("rid") or "") != str(rid):
                continue
            key = str(entry.get("rid") or "")
            if key and key in seen:
                # Один запрос может оставить две записи (статус из middleware и
                # traceback из обработчика) — оставляем ту, где больше деталей.
                index = seen[key]
                current = items[index]
                if entry.get("traceback") and not current.get("traceback"):
                    merged = {**current, **entry}
                    merged["duration_ms"] = entry.get("duration_ms") or current.get("duration_ms")
                    items[index] = merged
                else:
                    current["duration_ms"] = current.get("duration_ms") or entry.get("duration_ms")
                continue
            if key:
                seen[key] = len(items)
            items.append(entry)
            if len(items) >= take:
                break
        return items, candidate
    return [], None
