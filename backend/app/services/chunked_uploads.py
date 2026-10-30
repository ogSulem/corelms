"""Приём больших файлов частями, с продолжением после обрыва.

Один длинный запрос на файл в гигабайт обрывается на любом прокси: у Node в
Next.js есть свой предел времени на приём тела, у nginx и Caddy — свои. Поэтому
файл принимается кусками по 8 МБ: каждый кусок укладывается в доли секунды,
а если соединение всё же упало, клиент повторяет только этот кусок с того же
смещения и загрузка не начинается заново.

Куски складываются во временный каталог на диске (том backend_data). После
сборки файл читается целиком, проверяется размер и контрольная сумма, затем
уходит в S3 обычным путём — ровно так же, как при обычной загрузке.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from fastapi import HTTPException

from app.core.config import settings

log = logging.getLogger(__name__)

UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
META_NAME = "meta.json"
RESULT_NAME = "result.json"
BLOB_NAME = "blob.part"
# Один кусок не должен превращаться в полноценную загрузку: клиент режет по chunk_size.
MAX_CHUNK_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class UploadSession:
    id: str
    user_id: str
    kind: str
    filename: str
    size_bytes: int
    meta: dict


def _root() -> Path:
    """Каталог для недособранных файлов. /data — постоянный том backend-контейнера."""
    candidates = [str(getattr(settings, "upload_staging_dir", "") or "").strip(), "/tmp/corelms-uploads"]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".writable"
            probe.write_bytes(b"")
            probe.unlink()
            return path
        except OSError:
            continue
    return Path(tempfile.mkdtemp(prefix="corelms-uploads-"))


def chunk_size() -> int:
    value = int(getattr(settings, "upload_chunk_bytes", 8 * 1024 * 1024) or 8 * 1024 * 1024)
    return max(256 * 1024, min(value, MAX_CHUNK_BYTES))


def _ttl_seconds() -> int:
    return int(getattr(settings, "upload_session_ttl_hours", 24) or 24) * 3600


def _session_dir(upload_id: str) -> Path:
    if not UPLOAD_ID_RE.match(str(upload_id or "")):
        raise HTTPException(404, "Загрузка не найдена. Начните её заново.")
    return _root() / str(upload_id)


def sweep_stale() -> None:
    """Удаляем брошенные сессии: они занимают место на диске, но не нужны."""
    root = _root()
    deadline = time.time() - _ttl_seconds()
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.is_dir() or not UPLOAD_ID_RE.match(entry.name):
            continue
        try:
            if entry.stat().st_mtime < deadline:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            log.debug("chunked upload sweep failed for %s", entry, exc_info=True)


def create_session(*, user_id: str, kind: str, filename: str, size_bytes: int, meta: dict) -> UploadSession:
    sweep_stale()
    upload_id = uuid.uuid4().hex
    directory = _session_dir(upload_id)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"id": upload_id, "user_id": str(user_id), "kind": kind, "filename": filename,
               "size_bytes": int(size_bytes), "created_at": time.time(), "meta": meta}
    (directory / META_NAME).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (directory / BLOB_NAME).touch()
    return UploadSession(id=upload_id, user_id=str(user_id), kind=kind, filename=filename,
                         size_bytes=int(size_bytes), meta=meta)


def read_session(upload_id: str) -> UploadSession:
    directory = _session_dir(upload_id)
    meta_path = directory / META_NAME
    if not meta_path.is_file():
        raise HTTPException(404, "Загрузка не найдена. Начните её заново.")
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "Состояние загрузки повреждено. Начните её заново.") from exc
    return UploadSession(id=payload["id"], user_id=str(payload.get("user_id") or ""),
                         kind=str(payload.get("kind") or ""), filename=str(payload.get("filename") or ""),
                         size_bytes=int(payload.get("size_bytes") or 0), meta=dict(payload.get("meta") or {}))


def blob_path(upload_id: str) -> Path:
    return _session_dir(upload_id) / BLOB_NAME


def received_bytes(upload_id: str) -> int:
    path = blob_path(upload_id)
    try:
        return path.stat().st_size
    except OSError:
        return 0


async def append_chunk(upload_id: str, *, offset: int, stream: AsyncIterator[bytes], limit: int) -> int:
    """Дописывает кусок ровно с указанного смещения.

    Если сервер уже принял больше (клиент повторил кусок после таймаута),
    возвращаем фактическое смещение и ничего не портим — клиент продолжит с него.
    """
    path = blob_path(upload_id)
    current = received_bytes(upload_id)
    if offset != current:
        return current
    written = 0
    try:
        with open(path, "r+b") as handle:
            handle.seek(offset)
            async for chunk in stream:
                if not chunk:
                    continue
                written += len(chunk)
                if written > limit:
                    raise HTTPException(413, "Кусок больше разрешённого размера")
                handle.write(chunk)
            handle.truncate(offset + written)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(503, "Не удалось сохранить полученные данные. Повторите кусок.") from exc
    return offset + written


def checksum_and_size(upload_id: str) -> tuple[str, int]:
    path = blob_path(upload_id)
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def save_result(upload_id: str, payload: dict) -> None:
    """Результат завершённой сборки.

    Ответ мог не дойти до браузера (таймаут прокси, обрыв сети), поэтому повторный
    `complete` должен вернуть тот же результат, а не создать второй файл.
    """
    try:
        (_session_dir(upload_id) / RESULT_NAME).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        log.debug("chunked upload: cannot persist result", exc_info=True)


def read_result(upload_id: str) -> dict | None:
    path = _session_dir(upload_id) / RESULT_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def discard_blob(upload_id: str) -> None:
    """После успешной сборки тяжёлый файл больше не нужен, а результат остаётся для повтора."""
    try:
        blob_path(upload_id).unlink(missing_ok=True)
    except OSError:
        log.debug("chunked upload: cannot remove blob", exc_info=True)


def discard(upload_id: str) -> None:
    try:
        shutil.rmtree(_session_dir(upload_id), ignore_errors=True)
    except HTTPException:
        pass


def open_blob(upload_id: str):
    return open(blob_path(upload_id), "rb")


def staging_free_bytes() -> int:
    try:
        return int(shutil.disk_usage(_root()).free)
    except OSError:
        return 0


def require_free_space(size_bytes: int) -> None:
    """Большой файл не должен забить диск так, чтобы остановить базу и воркеры."""
    free = staging_free_bytes()
    if free and size_bytes > free * 0.8:
        raise HTTPException(507, "Недостаточно места на диске сервера для этого файла. Освободите место и повторите загрузку.")


def disk_usage_note() -> str | None:
    free = staging_free_bytes()
    return None if free <= 0 else f"{free // (1024 * 1024)} МБ свободно во временном хранилище"
