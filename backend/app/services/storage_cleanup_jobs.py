from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from rq import get_current_job

from app.core.config import settings
from app.services.storage import ensure_bucket_exists, get_s3_client


log = logging.getLogger(__name__)


def cleanup_admin_uploads_job(*, prefix: str = "uploads/admin/", ttl_hours: int | None = None) -> dict:
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
    }

    if job is not None:
        try:
            meta = dict(job.meta or {})
            meta.update(out)
            job.meta = meta
            job.save_meta()
        except Exception:
            pass

    log.info(
        "cleanup_admin_uploads_job: prefix=%s ttl_hours=%s deleted_objects=%s deleted_bytes=%s",
        prefix,
        ttl,
        deleted_objects,
        deleted_bytes,
    )

    return out
