from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from rq import get_current_job
from sqlalchemy import delete

from app.core.config import settings
from app.core.redis_client import get_redis
from app.db.session import SessionLocal
from app.models.asset import ContentAsset
from app.services.storage import ensure_bucket_exists, get_s3_client


log = logging.getLogger(__name__)


def cleanup_admin_uploads_job(*, prefix: str = "uploads/", ttl_hours: int | None = None) -> dict:
    """Best-effort cleanup of large uploaded ZIP artifacts.

    Deletes objects under `prefix` older than TTL. Designed to be safe to run repeatedly.
    """

    try:
        job = get_current_job()
    except Exception:
        job = None

    ensure_bucket_exists()
    s3 = get_s3_client()

    ttl = int(ttl_hours if ttl_hours is not None else getattr(settings, "uploads_admin_ttl_hours", 24))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl)

    deleted_objects = 0
    deleted_bytes = 0
    deleted_asset_rows = 0

    token: str | None = None
    while True:
        kwargs: dict[str, object] = {
            "Bucket": settings.s3_bucket,
            "Prefix": prefix,
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token

        resp = s3.list_objects_v2(**kwargs)
        contents = resp.get("Contents") or []

        to_delete: list[dict[str, str]] = []
        for obj in contents:
            key = obj.get("Key")
            if not key:
                continue
            lm = obj.get("LastModified")
            if not isinstance(lm, datetime):
                continue
            if lm.tzinfo is None:
                lm = lm.replace(tzinfo=timezone.utc)
            if lm <= cutoff:
                to_delete.append({"Key": str(key)})
                try:
                    deleted_bytes += int(obj.get("Size") or 0)
                except Exception:
                    pass

        if to_delete:
            try:
                s3.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": to_delete, "Quiet": True})
                deleted_objects += len(to_delete)

                # Product hardening: also remove ContentAsset rows for admin upload artifacts.
                # These objects are temporary and must not bloat the DB over time.
                try:
                    keys = [str(x.get("Key") or "").strip() for x in to_delete]
                    keys = [k for k in keys if k]
                    if keys:
                        db = SessionLocal()
                        try:
                            # Safety: keep it scoped strictly to the admin uploads prefix.
                            safe_keys = [k for k in keys if k.startswith(prefix)]
                            if safe_keys:
                                # Chunk to avoid large IN clauses.
                                step = 500
                                for i in range(0, len(safe_keys), step):
                                    chunk = safe_keys[i : i + step]
                                    res = db.execute(delete(ContentAsset).where(ContentAsset.object_key.in_(chunk)))
                                    try:
                                        deleted_asset_rows += int(res.rowcount or 0)
                                    except Exception:
                                        pass
                                db.commit()
                        finally:
                            db.close()
                except Exception:
                    log.exception("cleanup_admin_uploads_job: failed to delete ContentAsset rows")
            except Exception:
                log.exception("cleanup_admin_uploads_job: delete_objects failed")

        if not resp.get("IsTruncated"):
            break
        token = str(resp.get("NextContinuationToken") or "") or None

    out = {
        "ok": True,
        "prefix": prefix,
        "ttl_hours": ttl,
        "cutoff": cutoff.isoformat(),
        "deleted_objects": int(deleted_objects),
        "deleted_bytes": int(deleted_bytes),
        "deleted_asset_rows": int(deleted_asset_rows),
    }

    if job is not None:
        try:
            meta = dict(job.meta or {})
            meta.update(out)
            job.meta = meta
            job.save_meta()
        except Exception:
            log.debug("cleanup_admin_uploads_job: failed to save job meta", exc_info=True)

    log.info(
        "cleanup_admin_uploads_job: prefix=%s ttl_hours=%s deleted_objects=%s deleted_bytes=%s deleted_asset_rows=%s",
        prefix,
        ttl,
        deleted_objects,
        deleted_bytes,
        deleted_asset_rows,
    )

    return out


def cleanup_admin_multipart_uploads_job(
    *,
    prefix: str = "uploads/",
    ttl_hours: int | None = None,
    max_to_abort: int | None = None,
) -> dict:
    try:
        job = get_current_job()
    except Exception:
        job = None

    ensure_bucket_exists()
    s3 = get_s3_client()

    ttl = int(ttl_hours if ttl_hours is not None else getattr(settings, "uploads_admin_multipart_ttl_hours", 12))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl)
    cap = int(max_to_abort if max_to_abort is not None else getattr(settings, "uploads_admin_multipart_max_abort", 200))
    cap = max(1, min(cap, 2000))

    aborted = 0
    scanned = 0
    hb_check_errors = 0
    hb_delete_errors = 0

    r = None
    try:
        r = get_redis()
    except Exception:
        r = None

    key_marker: str | None = None
    upload_id_marker: str | None = None
    while True:
        if aborted >= cap:
            break

        kwargs: dict[str, object] = {
            "Bucket": settings.s3_bucket,
            "Prefix": prefix,
            "MaxUploads": 1000,
        }
        if key_marker and upload_id_marker:
            kwargs["KeyMarker"] = key_marker
            kwargs["UploadIdMarker"] = upload_id_marker

        try:
            resp = s3.list_multipart_uploads(**kwargs)
        except Exception:
            log.exception("cleanup_admin_multipart_uploads_job: list_multipart_uploads failed")
            break

        uploads = resp.get("Uploads") or []
        scanned += len(uploads)
        for u in uploads:
            if aborted >= cap:
                break
            try:
                key = str((u or {}).get("Key") or "").strip()
                upload_id = str((u or {}).get("UploadId") or "").strip()
                initiated = (u or {}).get("Initiated")
                if not key or not upload_id or not isinstance(initiated, datetime):
                    continue
                if initiated.tzinfo is None:
                    initiated = initiated.replace(tzinfo=timezone.utc)
                if initiated > cutoff:
                    continue

                if r is not None:
                    try:
                        hb_key = f"admin:multipart:last_seen:{key}:{upload_id}"
                        raw = r.get(hb_key)
                        if raw:
                            try:
                                s = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                            except Exception:
                                s = str(raw)
                            last_seen_ms = int(float(str(s).strip() or "0") or 0)
                            if last_seen_ms:
                                last_seen = datetime.fromtimestamp(last_seen_ms / 1000.0, tz=timezone.utc)
                                if last_seen > cutoff:
                                    continue
                    except Exception:
                        hb_check_errors += 1

                try:
                    s3.abort_multipart_upload(Bucket=settings.s3_bucket, Key=key, UploadId=upload_id)
                    aborted += 1
                    if r is not None:
                        try:
                            r.delete(f"admin:multipart:last_seen:{key}:{upload_id}")
                        except Exception:
                            hb_delete_errors += 1
                except Exception:
                    log.warning(
                        "cleanup_admin_multipart_uploads_job: abort failed bucket=%s key=%s upload_id=%s",
                        settings.s3_bucket,
                        key,
                        upload_id,
                    )
            except Exception:
                continue

        if not resp.get("IsTruncated"):
            break

        key_marker = str(resp.get("NextKeyMarker") or "") or None
        upload_id_marker = str(resp.get("NextUploadIdMarker") or "") or None
        if not key_marker or not upload_id_marker:
            break

    out = {
        "ok": True,
        "prefix": prefix,
        "ttl_hours": ttl,
        "cutoff": cutoff.isoformat(),
        "scanned_uploads": int(scanned),
        "aborted_uploads": int(aborted),
        "max_to_abort": int(cap),
    }

    if job is not None:
        try:
            meta = dict(job.meta or {})
            meta.update(out)
            job.meta = meta
            job.save_meta()
        except Exception:
            log.debug("cleanup_admin_multipart_uploads_job: failed to save job meta", exc_info=True)

    if (hb_check_errors or hb_delete_errors) and log.isEnabledFor(logging.DEBUG):
        log.debug(
            "cleanup_admin_multipart_uploads_job: redis heartbeat issues hb_check_errors=%s hb_delete_errors=%s",
            int(hb_check_errors),
            int(hb_delete_errors),
        )

    log.info(
        "cleanup_admin_multipart_uploads_job: prefix=%s ttl_hours=%s scanned=%s aborted=%s",
        prefix,
        ttl,
        scanned,
        aborted,
    )
    return out
