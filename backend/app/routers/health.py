from fastapi import APIRouter, HTTPException, Request
import hmac
from sqlalchemy import text

from app.core.queue import get_queue
from app.core.redis_client import get_redis
from app.core.security import require_cron_secret
from app.core.config import settings
from app.services.admin_uploads_cleanup import cleanup_admin_uploads_job
from app.services.storage import get_s3_client

router = APIRouter(tags=["health"])


def _require_cron_secret(request: Request) -> None:
    secret = str(getattr(settings, "cron_secret", "") or "").strip()
    if not secret:
        raise HTTPException(status_code=404, detail="not found")

    provided = str(request.headers.get("x-cron-secret") or "").strip()
    if not provided or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/live")
def live():
    return {"status": "live"}


@router.get("/health/ready")
def ready():
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail="db not ready") from e

    try:
        r = get_redis()
        r.ping()
    except Exception as e:
        raise HTTPException(status_code=503, detail="redis not ready") from e

    try:
        s3 = get_s3_client()
        s3.head_bucket(Bucket=settings.s3_bucket)
    except Exception as e:
        raise HTTPException(status_code=503, detail="s3 not ready") from e

    return {"status": "ready"}


@router.post("/health/cron/admin-uploads-cleanup")
def cron_admin_uploads_cleanup(request: Request):
    _require_cron_secret(request)

    interval_seconds = max(60, int(getattr(settings, "uploads_admin_cleanup_interval_minutes", 15)) * 60)
    lock_key = "locks:admin_uploads_cleanup"
    lock_ttl = max(60, interval_seconds - 5)

    r = get_redis()
    acquired = r.set(lock_key, "1", nx=True, ex=int(lock_ttl))
    if not acquired:
        return {"ok": True, "enqueued": False, "reason": "locked"}

    q = get_queue(str(settings.rq_queue_default))
    job = q.enqueue(
        cleanup_admin_uploads_job,
        ttl_hours=int(getattr(settings, "uploads_admin_ttl_hours", 6)),
        job_timeout=60 * 10,
        result_ttl=60 * 60,
        failure_ttl=60 * 60,
    )
    return {"ok": True, "enqueued": True, "job_id": str(job.id)}


@router.post("/health/cron/run-all")
def cron_run_all(request: Request):
    _require_cron_secret(request)

    results: dict[str, object] = {"ok": True, "tasks": {}}

    # 1) admin uploads cleanup
    try:
        interval_seconds = max(60, int(getattr(settings, "uploads_admin_cleanup_interval_minutes", 15)) * 60)
        lock_key = "locks:admin_uploads_cleanup"
        lock_ttl = max(60, interval_seconds - 5)

        r = get_redis()
        acquired = r.set(lock_key, "1", nx=True, ex=int(lock_ttl))
        if not acquired:
            results["tasks"]["admin_uploads_cleanup"] = {"ok": True, "enqueued": False, "reason": "locked"}
        else:
            q = get_queue(str(settings.rq_queue_default))
            job = q.enqueue(
                cleanup_admin_uploads_job,
                ttl_hours=int(getattr(settings, "uploads_admin_ttl_hours", 6)),
                job_timeout=60 * 10,
                result_ttl=60 * 60,
                failure_ttl=60 * 60,
            )
            results["tasks"]["admin_uploads_cleanup"] = {"ok": True, "enqueued": True, "job_id": str(job.id)}
    except Exception as e:
        results["tasks"]["admin_uploads_cleanup"] = {"ok": False, "error": str(e)}

    return results
