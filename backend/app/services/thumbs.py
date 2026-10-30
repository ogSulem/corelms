"""Превью файлов: кадр видео и уменьшенная копия фото.

Зачем отдельный сервис:

* списки материалов показывали полный оригинал — фото на 12 МБ грузилось
  целиком ради квадратика 44×44, а видео ради кадра скачивалось в браузер;
* ffmpeg уже есть в образе API, поэтому кадр можно снять сразу после загрузки,
  не дожидаясь медиа-воркера;
* превью лежит в S3 рядом с остальными производными объектами и удаляется
  вместе с оригиналом.

Исходник не скачивается на диск: ffmpeg читает его по подписанной ссылке
внутреннего адреса S3 и забирает только нужные байты.
"""
from __future__ import annotations

import logging
import pathlib
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.asset import ContentAsset
from app.models.media import AssetThumb
from app.services.storage import effective_bucket, get_s3_client

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "avif", "heic", "heif"}
VIDEO_EXTENSIONS = {"mp4", "mov", "m4v", "mkv", "avi", "webm", "wmv", "flv", "mpeg", "mpg", "mts", "m2ts", "3gp", "ogv"}
THUMB_MAX_SIDE = 512
THUMB_QUALITY = 4  # ffmpeg mjpeg: 2 — лучше, 31 — хуже
THUMB_TIMEOUT_SECONDS = 25
MAX_THUMB_BYTES = 3 * 1024 * 1024
STALE_PROCESSING = timedelta(minutes=10)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def thumb_kind(filename: str | None) -> str | None:
    ext = pathlib.PurePosixPath(str(filename or "")).suffix.lower().lstrip(".")
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return None


@dataclass(frozen=True)
class ThumbView:
    state: str
    bucket: str | None
    object_key: str | None
    size_bytes: int | None
    error: str | None


def current_thumb(db: Session, asset: ContentAsset) -> AssetThumb | None:
    return db.scalar(select(AssetThumb).where(AssetThumb.asset_id == asset.id,
        AssetThumb.source_version == asset.version, AssetThumb.source_bucket == asset.bucket,
        AssetThumb.source_object_key == asset.object_key))


def ensure_thumb(db: Session, asset: ContentAsset, *, retry: bool = False) -> AssetThumb | None:
    """Строка превью для текущей версии файла. Ничего не генерирует."""
    kind = thumb_kind(asset.original_filename)
    if not kind:
        return None
    db.execute(update(AssetThumb).where(AssetThumb.asset_id == asset.id,
        AssetThumb.source_version != asset.version, AssetThumb.state.in_(["pending", "processing"]))
        .values(state="skipped", updated_at=utcnow()))
    row = current_thumb(db, asset)
    if row is None:
        row = AssetThumb(asset_id=asset.id, source_version=asset.version, source_bucket=asset.bucket,
                         source_object_key=asset.object_key, kind=kind)
        db.add(row)
        db.flush()
        return row
    if retry and row.state in {"failed", "skipped"}:
        row.state, row.error, row.updated_at = "pending", None, utcnow()
    return row


def _presigned_url(asset: ContentAsset) -> str:
    """Ссылка на оригинал по внутреннему адресу S3: воркер не выходит в интернет."""
    return get_s3_client().generate_presigned_url(
        "get_object", Params={"Bucket": asset.bucket, "Key": asset.object_key}, ExpiresIn=900)


def _run(args: list[str], *, timeout: int = THUMB_TIMEOUT_SECONDS) -> bytes:
    result = subprocess.run(args, capture_output=True, timeout=timeout, check=False,
                            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"})
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-300:]
        raise RuntimeError(detail or "ffmpeg завершился с ошибкой")
    return result.stdout


def _scale_filter() -> str:
    # Только уменьшаем: маленькое фото не растягиваем и не тратим байты.
    return f"scale='min({THUMB_MAX_SIDE},iw)':'min({THUMB_MAX_SIDE},ih)':force_original_aspect_ratio=decrease"


def render_thumb(asset: ContentAsset, kind: str) -> bytes:
    """JPEG-кадр из видео или уменьшенная копия фото. Без записи на диск."""
    url = _presigned_url(asset)
    common = [settings.ffmpeg_binary, "-nostdin", "-hide_banner", "-loglevel", "error",
              "-protocol_whitelist", "http,https,tcp,tls,file", "-y"]
    if kind == "video":
        # Первый кадр часто чёрный (заставка/затухание) — берём кадр с 1-й секунды,
        # а если видео короче секунды, откатываемся на нулевую отметку.
        attempts = [["-ss", "1"], [""]]
        last: Exception | None = None
        for seek in attempts:
            args = [*common, *[a for a in seek if a], "-i", url, "-frames:v", "1",
                    "-an", "-sn", "-dn", "-vf", _scale_filter(), "-q:v", str(THUMB_QUALITY), "-f", "mjpeg", "pipe:1"]
            try:
                return _run(args)
            except Exception as exc:  # noqa: BLE001 — пробуем следующую отметку
                last = exc
        raise RuntimeError(f"Не удалось снять кадр: {last}") from last
    args = [*common, "-i", url, "-frames:v", "1", "-an", "-sn", "-dn",
            "-vf", _scale_filter(), "-q:v", str(THUMB_QUALITY), "-f", "mjpeg", "pipe:1"]
    return _run(args)


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """Размеры из SOF-маркера: нужно только для подсказки браузеру и диагностики."""
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        length = int.from_bytes(data[index + 2:index + 4], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            return (int.from_bytes(data[index + 7:index + 9], "big"),
                    int.from_bytes(data[index + 5:index + 7], "big"))
        index += 2 + max(2, length)
    return (0, 0)


def generate_thumb(db: Session, asset: ContentAsset, *, retry: bool = False) -> ThumbView | None:
    """Собирает превью, если его ещё нет. Безопасно вызывать из нескольких процессов.

    Работу забирает ровно один запрос: состояние переводится в `processing`
    условным UPDATE. Остальные сразу получают текущее состояние и показывают
    иконку — вместо того чтобы запускать свой ffmpeg.
    """
    row = ensure_thumb(db, asset, retry=retry)
    if row is None:
        return None
    if row.state == "ready" and row.object_key:
        return ThumbView(row.state, row.bucket, row.object_key, row.size_bytes, row.error)
    if row.state == "processing" and row.updated_at:
        stamp = row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=timezone.utc)
        if stamp > utcnow() - STALE_PROCESSING:
            return ThumbView(row.state, row.bucket, row.object_key, row.size_bytes, row.error)
    claim = db.execute(update(AssetThumb)
        .where(AssetThumb.id == row.id, AssetThumb.state.in_(["pending", "failed", "skipped", "processing"]))
        .values(state="processing", error=None, updated_at=utcnow()))
    db.commit()
    if not claim.rowcount:
        db.refresh(row)
        return ThumbView(row.state, row.bucket, row.object_key, row.size_bytes, row.error)
    try:
        data = render_thumb(asset, row.kind)
        if not data or len(data) < 128:
            raise RuntimeError("ffmpeg вернул пустой кадр")
        if len(data) > MAX_THUMB_BYTES:
            raise RuntimeError("Превью получилось слишком большим")
        bucket = effective_bucket()
        key = f"thumbs/{asset.id}/{asset.version}/{uuid.uuid4().hex}.jpg"
        get_s3_client().put_object(Bucket=bucket, Key=key, Body=data, ContentType="image/jpeg",
                                   CacheControl="private, max-age=31536000, immutable")
        width, height = _jpeg_size(data)
        row = db.scalar(select(AssetThumb).where(AssetThumb.id == row.id))
        if row is None:
            # Файл удалили, пока мы готовили кадр: объект не оставляем.
            try:
                get_s3_client().delete_object(Bucket=bucket, Key=key)
            except Exception:
                log.warning("thumb cleanup failed for %s", key, exc_info=True)
            return None
        row.state, row.bucket, row.object_key = "ready", bucket, key
        row.size_bytes, row.width, row.height, row.error, row.updated_at = len(data), width, height, None, utcnow()
        db.commit()
        return ThumbView(row.state, row.bucket, row.object_key, row.size_bytes, None)
    except Exception as exc:  # noqa: BLE001 — превью не должно ломать просмотр
        log.info("thumb generation failed for %s: %s", asset.id, exc)
        row = db.scalar(select(AssetThumb).where(AssetThumb.id == row.id))
        if row is not None:
            row.state, row.error, row.updated_at = "failed", str(exc)[:500], utcnow()
            db.commit()
        return ThumbView("failed", None, None, None, str(exc)[:500])


def process_thumb_job(asset_id: str) -> dict:
    """Фоновая задача для медиа-очереди: прогреть превью сразу после загрузки."""
    from app.db.session import SessionLocal

    try:
        aid = uuid.UUID(str(asset_id))
    except ValueError:
        return {"ok": False, "error": "bad asset id"}
    with SessionLocal() as db:
        asset = db.get(ContentAsset, aid)
        if asset is None:
            return {"ok": True, "skipped": True}
        view = generate_thumb(db, asset)
        return {"ok": bool(view and view.state == "ready"), "state": view.state if view else "skipped"}


def enqueue_thumb(asset_id: uuid.UUID | str) -> None:
    """Тёплый запуск через медиа-очередь. Отсутствие воркера не мешает: превью
    всё равно соберётся при первом открытии списка."""
    try:
        from app.core.queue import get_queue

        get_queue(settings.rq_queue_media).enqueue(process_thumb_job, str(asset_id),
            job_timeout=120, result_ttl=600, failure_ttl=3600, meta={"job_kind": "thumb", "asset_id": str(asset_id)})
    except Exception:
        log.debug("thumb enqueue skipped", exc_info=True)


def thumb_keys(db: Session, asset_id: uuid.UUID) -> list[tuple[str, str]]:
    """Объекты превью для удаления вместе с файлом."""
    out: list[tuple[str, str]] = []
    for row in db.scalars(select(AssetThumb).where(AssetThumb.asset_id == asset_id)):
        if row.object_key and row.bucket:
            out.append((row.bucket, row.object_key))
    return out


def delete_thumbs(db: Session, asset_id: uuid.UUID) -> None:
    from sqlalchemy import delete as sql_delete

    db.execute(sql_delete(AssetThumb).where(AssetThumb.asset_id == asset_id))


__all__ = ["IMAGE_EXTENSIONS", "VIDEO_EXTENSIONS", "thumb_kind", "ensure_thumb", "generate_thumb",
           "process_thumb_job", "enqueue_thumb", "thumb_keys", "delete_thumbs", "current_thumb"]
