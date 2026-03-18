from __future__ import annotations

import json
import uuid
import urllib.parse
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from botocore.exceptions import ClientError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.core.security import get_current_user, require_roles
from app.core.security_audit_log import audit_log
from app.db.session import get_db
from app.models.asset import ContentAsset
from app.models.audit import LearningEvent, LearningEventType
from app.models.module import Module, Submodule
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.user import User, UserRole
from app.schemas.asset import AssetCreateRequest, AssetCreateResponse, AssetGetUrlResponse
from app.services.skills import record_activity_and_award_xp
from app.services.storage import get_s3_client, presign_get, presign_put

router = APIRouter(prefix="/assets", tags=["assets"])


log = logging.getLogger(__name__)


def _asset_access_guard(*, db: Session, user: User, aid: uuid.UUID, asset: ContentAsset) -> tuple[str | None, str | None]:
    # Hardening: avoid leaking arbitrary assets by UUID.
    # - Non-admin users must only access assets that are part of active learning content.
    # - Admin upload ZIP artifacts must never be downloadable by non-admins.
    object_key = str(asset.object_key or "")
    if user.role != UserRole.admin and object_key.startswith("uploads/admin/"):
        raise HTTPException(status_code=403, detail="forbidden")

    if user.role != UserRole.admin and object_key.startswith("uploads/quickstart/"):
        return None, None

    if user.role != UserRole.admin:
        linked_to_active = (
            db.scalar(
                select(func.count(ContentAsset.id))
                .select_from(ContentAsset)
                .join(SubmoduleAssetMap, SubmoduleAssetMap.asset_id == ContentAsset.id)
                .join(Submodule, Submodule.id == SubmoduleAssetMap.submodule_id)
                .join(Module, Module.id == Submodule.module_id)
                .where(ContentAsset.id == aid, Module.is_active == True)  # noqa: E712
            )
            or 0
        )

        module_prefix_active = 0
        if object_key.startswith("modules/"):
            parts = object_key.split("/")
            seg = parts[1] if len(parts) >= 2 else ""
            mid = ""
            if seg:
                if "__" in seg:
                    mid = seg.split("__")[-1]
                else:
                    mid = seg
            if mid:
                module_prefix_active = (
                    db.scalar(select(func.count(Module.id)).select_from(Module).where(Module.id == mid, Module.is_active == True))  # noqa: E712
                    or 0
                )

        if int(linked_to_active) <= 0 and int(module_prefix_active) <= 0:
            raise HTTPException(status_code=403, detail="forbidden")

    module_id = None
    submodule_id = None
    try:
        row = db.execute(
            select(Submodule.id, Module.id)
            .select_from(SubmoduleAssetMap)
            .join(Submodule, Submodule.id == SubmoduleAssetMap.submodule_id)
            .join(Module, Module.id == Submodule.module_id)
            .where(SubmoduleAssetMap.asset_id == asset.id)
            .limit(1)
        ).first()
        if row:
            submodule_id = str(row[0]) if row[0] else None
            module_id = str(row[1]) if row[1] else None
    except Exception:
        log.debug("assets: failed to resolve module/submodule ids for asset", exc_info=True)
        module_id = None
        submodule_id = None
    return module_id, submodule_id


@router.post("/presign-upload", response_model=AssetCreateResponse)
def presign_upload(
    request: Request,
    body: AssetCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="asset_presign_upload", limit=30, window_seconds=60),
):
    existing = db.scalar(select(ContentAsset).where(ContentAsset.object_key == body.object_key))
    if existing is not None:
        raise HTTPException(status_code=409, detail="object_key already exists")

    asset = ContentAsset(
        bucket=settings.s3_bucket,
        object_key=body.object_key,
        original_filename=body.original_filename,
        mime_type=body.mime_type,
        created_by=user.id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    url = presign_put(object_key=asset.object_key, content_type=asset.mime_type)
    audit_log(
        db=db,
        request=request,
        event_type="admin_presign_asset_upload",
        actor_user_id=user.id,
        meta={"asset_id": str(asset.id), "object_key": asset.object_key, "mime_type": asset.mime_type},
    )
    db.commit()
    return AssetCreateResponse(asset_id=str(asset.id), upload_url=url)


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

    # Office Online viewer requires a stable public URL and often behaves better
    # with a correct Content-Type. Also give Office embeds a longer TTL.
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
        s3.head_object(Bucket=settings.s3_bucket, Key=str(asset.object_key or ""))
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
        object_key=asset.object_key,
        response_content_type=response_ct,
        response_content_disposition=disposition,
        expires_seconds=int(expires_seconds),
    )
    return AssetGetUrlResponse(asset_id=str(asset.id), download_url=url)


@router.get("/{asset_id}/stream")
def stream_asset(
    request: Request,
    asset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    range_header: str | None = Header(default=None, alias="Range"),
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

    record_activity_and_award_xp(db, user_id=str(user.id), xp=0)
    try:
        meta = {
            "action": "stream",
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

    s3 = get_s3_client()
    object_key = str(asset.object_key or "")
    if not object_key:
        raise HTTPException(status_code=404, detail="asset not found")

    content_type = str(asset.mime_type or "").strip() or "application/octet-stream"
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

    ct_l = content_type.lower()
    allowed = False
    try:
        if ct_l == "application/pdf":
            allowed = True
        elif ct_l.startswith("image/"):
            allowed = True
        elif ct_l.startswith("video/"):
            allowed = True
        elif ct_l.startswith("text/"):
            allowed = True
    except Exception:
        allowed = False
    if not allowed:
        raise HTTPException(status_code=415, detail="unsupported media type")

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
        while True:
            chunk = body.read(1024 * 512)
            if not chunk:
                break
            yield chunk

    try:
        kwargs: dict[str, object] = {"Bucket": settings.s3_bucket, "Key": object_key}

        # If Range is requested, validate against object size and normalize to a concrete range.
        if range_value_l.startswith("bytes="):
            try:
                head = s3.head_object(Bucket=settings.s3_bucket, Key=object_key)
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
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
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
