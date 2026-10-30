from __future__ import annotations

import json
import uuid
import urllib.parse
import logging
import mimetypes
from pathlib import PurePath
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from botocore.exceptions import ClientError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.core.security import get_current_user, require_roles
from app.core.security_audit_log import audit_log
from app.db.session import get_db
from app.models.asset import ContentAsset
from app.models.sales import SalesEntry
from app.services.media import current_rendition, stage_rendition, asset_is_active
from app.models.audit import LearningEvent, LearningEventType
from app.models.module import Module, Submodule
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.user import User, UserRole
from app.schemas.asset import AssetCreateRequest, AssetCreateResponse, AssetGetUrlResponse
from app.services.skills import record_activity_and_award_xp
from app.services.access import is_admin, accessible_modules_clause
from app.services.document_preview import MAX_BYTES, build_preview, preview_slot
from app.services.content import referenced_storage_keys
from app.services.storage import get_s3_client, presign_get
from app.services.thumbs import current_thumb, generate_thumb, thumb_kind

router = APIRouter(prefix="/assets", tags=["assets"])


log = logging.getLogger(__name__)


def _asset_access_guard(*, db: Session, user: User, aid: uuid.UUID, asset: ContentAsset) -> tuple[str | None, str | None]:
    sales = db.scalar(select(SalesEntry).where(SalesEntry.asset_id == aid))
    if sales:
        from app.services.sales_library import path_is_visible
        if user.role != UserRole.superadmin and (asset.is_archived or sales.is_archived or not path_is_visible(db, sales.section, sales.path)):
            raise HTTPException(404, "Материал недоступен")
        return None, None
    if is_admin(user):
        return (str(asset.module_id) if asset.module_id else None), None
    if asset.is_archived:
        raise HTTPException(404, "Материал недоступен")
    if str(asset.object_key or "").startswith("uploads/quickstart/"):
        return None, None
    links = db.execute(select(Submodule.id, Submodule.module_id, Submodule.is_archived)
        .join(SubmoduleAssetMap, SubmoduleAssetMap.submodule_id == Submodule.id)
        .where(SubmoduleAssetMap.asset_id == aid)).all()
    candidates = {mid for _, mid, archived in links if not archived}
    if not links and asset.module_id:
        candidates.add(asset.module_id)
    allowed = db.scalar(select(Module.id).where(Module.id.in_(candidates), accessible_modules_clause(user)).limit(1))
    if allowed is None:
        raise HTTPException(404, "Материал недоступен")
    sub_id = next((sid for sid, mid, archived in links if mid == allowed and not archived), None)
    return str(allowed), str(sub_id) if sub_id else None


@router.post("/presign-upload", response_model=AssetCreateResponse)
def presign_upload(
    request: Request,
    body: AssetCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="asset_presign_upload", limit=30, window_seconds=60),
):
    if body.object_key in referenced_storage_keys(db):
        raise HTTPException(status_code=409, detail="object_key already exists")

    raise HTTPException(410, "Прямая запись в произвольные S3-ключи отключена. Загружайте файлы через редактор модуля или библиотеку продаж: они сохраняют оригиналы и версии.")


@router.get("/{asset_id}/presign-download", response_model=AssetGetUrlResponse)
def presign_download(
    request: Request,
    asset_id: str,
    action: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: object = rate_limit(key_prefix="asset_presign_download", limit=120, window_seconds=60),
):
    try:
        aid = uuid.UUID(asset_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid asset id") from e

    asset = db.scalar(select(ContentAsset).where(ContentAsset.id == aid))
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")

    module_id, submodule_id = _asset_access_guard(db=db, user=user, aid=aid, asset=asset)

    # Count asset views as activity for streak, but do not award XP.
    # Important: update streak BEFORE inserting the learning event to avoid autoflush affecting streak init.
    record_activity_and_award_xp(db, user_id=str(user.id), xp=0)

    # Enrich meta: this is the most reliable place to log file-level activity.
    # Note: we intentionally treat "presign download" as a learning event, because it reflects intent to open/download.
    act = "view"
    if str(action or "").strip().lower() == "download":
        act = "download"

    filename = str(asset.original_filename or "").strip() or "file"
    # Hardening: browsers/PDF viewers may mis-handle Content-Disposition filename* values
    # that contain path separators (e.g. "a/b/c.pdf" -> "%2F" in filename*).
    # Use basename only.
    try:
        filename = filename.replace("\\", "/")
        if "/" in filename:
            filename = filename.split("/")[-1].strip() or "file"
    except Exception:
        log.debug("assets: filename normalization failed", exc_info=True)
    quoted = urllib.parse.quote(filename, safe="")
    disposition = f"inline; filename*=UTF-8''{quoted}"
    if act == "download":
        disposition = f"attachment; filename*=UTF-8''{quoted}"

    meta = {
        "action": act,
        "filename": str(asset.original_filename or ""),
        "object_key": str(asset.object_key or ""),
        "mime_type": str(asset.mime_type or ""),
        "module_id": module_id,
        "submodule_id": submodule_id,
    }

    db.add(
        LearningEvent(
            user_id=user.id,
            type=LearningEventType.asset_viewed,
            ref_id=asset.id,
            meta=json.dumps(meta, ensure_ascii=False),
        )
    )
    db.commit()

    audit_log(
        db=db,
        request=request,
        event_type="asset_presign_download",
        actor_user_id=user.id,
        meta={"asset_id": str(asset.id), "object_key": str(asset.object_key), "mime_type": str(asset.mime_type or "")},
    )
    db.commit()

    expires_seconds = 300

    # Keep MIME metadata accurate for downloading Office originals.
    original_name_l = str(asset.original_filename or "").strip().lower()
    ext = ""
    try:
        if "." in original_name_l:
            ext = original_name_l.rsplit(".", 1)[-1].strip()
    except Exception:
        ext = ""
    office_ct_by_ext: dict[str, str] = {
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "ppt": "application/vnd.ms-powerpoint",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xls": "application/vnd.ms-excel",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    is_office_ext = ext in office_ct_by_ext
    if act == "view" and is_office_ext:
        expires_seconds = max(int(expires_seconds), 900)

    if act == "view" and is_office_ext:
        disposition = "inline"

    # Media playback can exceed short presign TTLs; allow a longer view window
    # to avoid mid-session expiration. This keeps load off the backend.
    try:
        ct_l = str(asset.mime_type or "").strip().lower()
        is_video = ct_l.startswith("video/") or ext in {"mp4", "webm", "mov", "mkv"}
        is_audio = ct_l.startswith("audio/") or ext in {"mp3", "wav", "ogg", "m4a"}
        is_pdf = (ct_l == "application/pdf") or (ext == "pdf")
        if act == "view" and (is_video or is_audio):
            expires_seconds = max(int(expires_seconds), 60 * 60)
        elif act == "view" and is_pdf:
            expires_seconds = max(int(expires_seconds), 15 * 60)
    except Exception:
        pass

    response_ct = str(asset.mime_type or "").strip() or None
    if is_office_ext:
        if not response_ct or response_ct.lower() in {"application/octet-stream", "binary/octet-stream"}:
            response_ct = office_ct_by_ext.get(ext) or response_ct

    # Hardening: if the object was manually deleted from storage, return 404 (not a broken presign URL).
    try:
        s3 = get_s3_client()
        s3.head_object(Bucket=asset.bucket, Key=str(asset.object_key or ""))
    except ClientError as e:
        code = str((e.response or {}).get("Error", {}).get("Code") or "").strip()
        status = int((e.response or {}).get("ResponseMetadata", {}).get("HTTPStatusCode") or 0)
        if code in {"NoSuchKey", "NotFound"} or status == 404:
            raise HTTPException(status_code=404, detail="file missing in storage") from e
        raise
    except Exception:
        # If storage is temporarily unavailable, keep behavior consistent with current API contract.
        raise HTTPException(status_code=503, detail="storage unavailable")

    url = presign_get(
        object_key=asset.object_key, bucket=asset.bucket,
        response_content_type=response_ct,
        response_content_disposition=disposition,
        expires_seconds=int(expires_seconds),
    )
    return AssetGetUrlResponse(asset_id=str(asset.id), download_url=url)


@router.get("/{asset_id}/download")
@router.get("/{asset_id}/stream")
def stream_asset(
    request: Request,
    asset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    range_header: str | None = Header(default=None, alias="Range"),
    variant: Literal["original", "browser"] = Query(default="original"),
    # `thumb=1` is used by list previews: it never writes a learning event and may be cached.
    thumb: bool = Query(default=False),
    _: object = rate_limit(key_prefix="asset_stream", limit=240, window_seconds=60),
):
    try:
        aid = uuid.UUID(asset_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid asset id") from e

    asset = db.scalar(select(ContentAsset).where(ContentAsset.id == aid))
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")

    module_id, submodule_id = _asset_access_guard(db=db, user=user, aid=aid, asset=asset)
    downloading = request.url.path.endswith("/download")
    snapshot = {name: getattr(asset, name) for name in ("id", "bucket", "object_key", "mime_type", "original_filename", "version")}
    if variant == "browser" and not downloading:
        rendition = current_rendition(db, asset)
        if not rendition or rendition.state != "ready" or not rendition.object_key:
            raise HTTPException(409, "Копия для браузера ещё не готова. Оригинал доступен для скачивания.")
        snapshot.update(bucket=rendition.bucket, object_key=rendition.object_key, mime_type=rendition.mime_type,
            original_filename=str(PurePath(asset.original_filename).with_suffix(".mp4" if rendition.mime_type == "video/mp4" else ".pdf")))


    # Thumbnails stay out of the learning journal: a file listed in a cabinet is not «просмотр материала».
    if not thumb:
        record_activity_and_award_xp(db, user_id=str(user.id), xp=0)
        try:
            meta = {
                "action": "download" if downloading else "stream",
                "filename": str(asset.original_filename or ""),
                "object_key": str(asset.object_key or ""),
                "mime_type": str(asset.mime_type or ""),
                "module_id": module_id,
                "submodule_id": submodule_id,
            }
            db.add(
                LearningEvent(
                    user_id=user.id,
                    type=LearningEventType.asset_viewed,
                    ref_id=asset.id,
                    meta=json.dumps(meta, ensure_ascii=False),
                )
            )
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    asset = SimpleNamespace(**snapshot)
    s3 = get_s3_client()
    object_key = str(asset.object_key or "")
    if not object_key:
        raise HTTPException(status_code=404, detail="asset not found")

    content_type = mimetypes.guess_type(asset.original_filename)[0] or str(asset.mime_type or "").strip() or "application/octet-stream"
    filename = str(asset.original_filename or "").strip() or "file"
    # Hardening: Edge/PDF viewer may block if Content-Disposition filename* contains path separators.
    # Use basename only.
    try:
        filename = filename.replace("\\", "/")
        if "/" in filename:
            filename = filename.split("/")[-1].strip() or "file"
    except Exception:
        pass
    # Best-effort: ensure correct PDF Content-Type.
    try:
        ext = ""
        original_name_l = str(asset.original_filename or "").strip().lower()
        if "." in original_name_l:
            ext = original_name_l.rsplit(".", 1)[-1].strip()
        if ext == "pdf" and content_type.lower() in {"application/octet-stream", "binary/octet-stream"}:
            content_type = "application/pdf"
    except Exception:
        pass
    quoted = urllib.parse.quote(filename, safe="")
    disposition = f"inline; filename*=UTF-8''{quoted}"

    extension = PurePath(filename).suffix.lower()
    # Never render uploaded HTML/SVG/XML on the authenticated application's origin.
    safe_inline = extension in {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".mp4", ".webm", ".mov", ".mp3", ".wav", ".ogg", ".m4a", ".flac"}
    if not downloading and not safe_inline:
        raise HTTPException(415, "Для этого формата используйте предпросмотр или скачайте оригинал")
    if downloading:
        disposition = f"attachment; filename*=UTF-8''{quoted}"

    # Parse Range: bytes=start-end
    range_value = str(range_header or "").strip()
    range_value_l = range_value.lower()
    start: int | None = None
    end: int | None = None
    suffix_len: int | None = None
    if range_value_l.startswith("bytes="):
        try:
            spec = range_value_l.split("=", 1)[1]
            part = spec.split(",", 1)[0].strip()
            a, b = part.split("-", 1)
            a = a.strip()
            b = b.strip()
            if a and b:
                start = int(a)
                end = int(b)
            elif a and (not b):
                start = int(a)
                end = None
            elif (not a) and b:
                suffix_len = int(b)
            else:
                start = None
                end = None
        except Exception:
            start = None
            end = None
            suffix_len = None

    def _body_iter(body):
        try:
            while True:
                chunk = body.read(1024 * 512)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    try:
        kwargs: dict[str, object] = {"Bucket": asset.bucket, "Key": object_key}

        # If Range is requested, validate against object size and normalize to a concrete range.
        if range_value_l.startswith("bytes="):
            try:
                head = s3.head_object(Bucket=asset.bucket, Key=object_key)
                size_total = int(head.get("ContentLength") or 0)
            except ClientError as e:
                code = str((e.response or {}).get("Error", {}).get("Code") or "").strip()
                status = int((e.response or {}).get("ResponseMetadata", {}).get("HTTPStatusCode") or 0)
                if code in {"NoSuchKey", "NotFound"} or status == 404:
                    raise HTTPException(status_code=404, detail="file missing in storage") from e
                raise HTTPException(status_code=503, detail="storage unavailable") from e
            except Exception as e:
                raise HTTPException(status_code=503, detail="storage unavailable") from e

            # Normalize / validate.
            invalid = False
            if size_total <= 0:
                invalid = True
            elif suffix_len is not None:
                if suffix_len <= 0:
                    invalid = True
                else:
                    take = min(int(suffix_len), int(size_total))
                    start = int(size_total) - take
                    end = int(size_total) - 1
            else:
                if start is None:
                    invalid = True
                else:
                    if start < 0:
                        invalid = True
                    if end is not None and end < start:
                        invalid = True
                    if start >= size_total:
                        invalid = True
                    if end is not None and end >= size_total:
                        end = size_total - 1

            if invalid:
                headers = {"Accept-Ranges": "bytes", "Content-Range": f"bytes */{int(size_total)}"}
                raise HTTPException(status_code=416, detail="invalid range", headers=headers)

            if start is not None and end is None:
                kwargs["Range"] = f"bytes={start}-"
            elif start is not None and end is not None:
                kwargs["Range"] = f"bytes={start}-{end}"

        obj = s3.get_object(**kwargs)
        body = obj.get("Body")
        if body is None:
            raise HTTPException(status_code=404, detail="asset not found")

        headers = {
            "Content-Disposition": disposition,
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=600" if thumb else "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Frame-Options": "SAMEORIGIN",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; object-src 'self'; frame-ancestors 'self'",
        }
        if obj.get("ContentRange"):
            headers["Content-Range"] = str(obj.get("ContentRange"))

        status_code = 206 if ("Range" in kwargs) else 200
        resp = StreamingResponse(
            _body_iter(body),
            media_type=content_type,
            status_code=status_code,
            headers=headers,
        )

        # Best-effort: set Content-Length if provided by S3 response.
        try:
            clen = obj.get("ContentLength")
            if clen is not None:
                resp.headers["Content-Length"] = str(int(clen))
        except Exception:
            pass

        return resp
    except HTTPException:
        raise
    except ClientError as e:
        code = str((e.response or {}).get("Error", {}).get("Code") or "").strip()
        status = int((e.response or {}).get("ResponseMetadata", {}).get("HTTPStatusCode") or 0)
        if code in {"NoSuchKey", "NotFound"} or status == 404:
            raise HTTPException(status_code=404, detail="file missing in storage") from e
        raise HTTPException(status_code=503, detail="storage unavailable") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="failed to stream asset") from e


@router.get("/{asset_id}/preview")
def preview_asset(
    asset_id: uuid.UUID, sheet: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
    _: object = rate_limit(key_prefix="asset_preview", limit=60, window_seconds=60),
):
    asset = db.get(ContentAsset, asset_id)
    if asset is None:
        raise HTTPException(404, "Файл не найден")
    module_id, submodule_id = _asset_access_guard(db=db, user=user, aid=asset_id, asset=asset)
    if asset.size_bytes and asset.size_bytes > MAX_BYTES:
        raise HTTPException(413, "Файл больше 25 МБ. Для просмотра скачайте оригинал.")
    with preview_slot():
        try:
            obj = get_s3_client().get_object(Bucket=asset.bucket, Key=asset.object_key)
            body = obj["Body"]
            try:
                if int(obj.get("ContentLength") or 0) > MAX_BYTES:
                    raise HTTPException(413, "Файл больше 25 МБ. Для просмотра скачайте оригинал.")
                data = body.read(MAX_BYTES + 1)
            finally:
                body.close()
        except HTTPException:
            raise
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            raise HTTPException(404 if code in {"404", "NoSuchKey", "NotFound"} else 503,
                                "Файл не найден в хранилище" if code in {"404", "NoSuchKey", "NotFound"} else "Хранилище временно недоступно") from exc
        except Exception as exc:
            raise HTTPException(503, "Хранилище временно недоступно. Повторите попытку.") from exc
        preview = build_preview(data, asset.original_filename, sheet=sheet)
    record_activity_and_award_xp(db, user_id=str(user.id), xp=0)
    db.add(LearningEvent(user_id=user.id, type=LearningEventType.asset_viewed, ref_id=asset.id,
                        meta=json.dumps({"action": "preview", "module_id": module_id, "submodule_id": submodule_id,
                                         "filename": asset.original_filename}, ensure_ascii=False)))
    db.commit()
    from fastapi.responses import JSONResponse
    return JSONResponse({**preview, "asset_id": str(asset.id), "version": asset.version}, headers={"Cache-Control": "private, no-store"})


def _iter_body(body):
    try:
        while True:
            chunk = body.read(1024 * 256)
            if not chunk:
                break
            yield chunk
    finally:
        body.close()


@router.get("/{asset_id}/thumb")
def asset_thumb(
    asset_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    refresh: bool = Query(default=False, description="Пересобрать превью (только админ)"),
    _: object = rate_limit(key_prefix="asset_thumb", limit=600, window_seconds=60),
):
    """Маленькое превью файла для списков: кадр видео или уменьшенное фото.

    Превью — обычная картинка, поэтому список не скачивает видео и не тянет
    оригинал фото на 12 МБ. Пока превью нет, ответ 404 с `Retry-After`:
    список покажет иконку и перезапросит картинку позже.
    """
    asset = db.scalar(select(ContentAsset).where(ContentAsset.id == asset_id))
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    _asset_access_guard(db=db, user=user, aid=asset_id, asset=asset)
    if thumb_kind(asset.original_filename) is None:
        raise HTTPException(status_code=404, detail="у этого формата нет превью")

    row = current_thumb(db, asset)
    if refresh and is_admin(user):
        row = generate_thumb(db, asset, retry=True)
    elif row is None or row.state != "ready" or not row.object_key:
        row = generate_thumb(db, asset)

    if row is None or row.state != "ready" or not row.object_key:
        headers = {"Cache-Control": "no-store", "Retry-After": "6"}
        raise HTTPException(status_code=404, detail="превью ещё готовится", headers=headers)

    etag = '"' + str(row.object_key).rsplit("/", 1)[-1].split(".")[0] + '"'
    common = {
        "Cache-Control": "private, max-age=604800",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    }
    if str(request.headers.get("if-none-match") or "").strip() == etag:
        return Response(status_code=304, headers=common)
    try:
        obj = get_s3_client().get_object(Bucket=str(row.bucket), Key=str(row.object_key))
    except ClientError as exc:
        code = str((exc.response or {}).get("Error", {}).get("Code") or "")
        if code in {"NoSuchKey", "NotFound"}:
            raise HTTPException(status_code=404, detail="превью не найдено в хранилище") from exc
        raise HTTPException(status_code=503, detail="storage unavailable") from exc
    body = obj.get("Body")
    if body is None:
        raise HTTPException(status_code=404, detail="превью не найдено в хранилище")
    common["Content-Length"] = str(int(obj.get("ContentLength") or row.size_bytes or 0))
    return StreamingResponse(_iter_body(body), media_type="image/jpeg", headers=common)


@router.get("/{asset_id}/viewer")
def asset_viewer(asset_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                 _: object = rate_limit(key_prefix="asset_viewer", limit=120, window_seconds=60)):
    asset = db.scalar(select(ContentAsset).where(ContentAsset.id == asset_id).with_for_update())
    if not asset:
        raise HTTPException(404, "Материал недоступен")
    _asset_access_guard(db=db, user=user, aid=asset_id, asset=asset)
    row = current_rendition(db, asset)
    if (row is None or row.state == "skipped") and asset_is_active(db, asset):
        row = stage_rendition(db, asset)
        db.commit()
    return {"state": row.state if row else "original", "source_version": asset.version,
            "mime_type": row.mime_type if row and row.state == "ready" else None,
            "error": row.error if row else None, "can_retry": is_admin(user) and asset_is_active(db, asset) and (user.role == UserRole.superadmin or not db.scalar(select(SalesEntry.id).where(SalesEntry.asset_id == asset.id)))}


@router.post("/{asset_id}/viewer/retry", status_code=202)
def retry_asset_viewer(asset_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(require_roles(UserRole.admin)),
                       _: object = rate_limit(key_prefix="asset_viewer_retry", limit=20, window_seconds=60)):
    asset = db.scalar(select(ContentAsset).where(ContentAsset.id == asset_id).with_for_update())
    if not asset or not asset_is_active(db, asset):
        raise HTTPException(404, "Активный материал не найден")
    if db.scalar(select(SalesEntry.id).where(SalesEntry.asset_id == asset.id)) and user.role != UserRole.superadmin:
        raise HTTPException(403, "Только суперадминистратор управляет файлами продаж")
    row = stage_rendition(db, asset, retry=True)
    if not row:
        raise HTTPException(422, "Этот формат не требует подготовки")
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="asset_rendition_requested", meta={"asset_id": str(asset.id), "version": asset.version})
    db.commit()
    return {"state": row.state}
