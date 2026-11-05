from fastapi import APIRouter, HTTPException, Request, Response
import hmac
import os
from datetime import datetime, timezone
from sqlalchemy import text

from app.core.rate_limit import rate_limit
from app.core.redis_client import get_redis
from app.core.config import settings
from app.services.maintenance_schedule import run_due_tasks
from app.services.storage import effective_bucket, get_s3_client

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


@router.head("/health", include_in_schema=False)
def health_head():
    """Мониторинг и `curl -I` шлют HEAD: он должен отвечать, а не падать 405."""
    return Response(status_code=200)


_STARTED_AT = datetime.now(timezone.utc).isoformat()


@router.get("/health/version")
def version():
    """Какая версия кода реально запущена.

    Нужно, чтобы «изменения не применились» проверялось фактом, а не догадкой:
    deploy/update.sh проставляет APP_VERSION (короткий git-хеш) при пересборке.
    """
    return {
        "version": str(os.environ.get("APP_VERSION") or "dev").strip() or "dev",
        "started_at": _STARTED_AT,
        "pid": os.getpid(),
    }


@router.head("/health/version", include_in_schema=False)
def version_head():
    return Response(status_code=200)


@router.get("/health/live")
def live():
    return {"status": "live"}


@router.head("/health/live", include_in_schema=False)
def live_head():
    return Response(status_code=200)


def _check_ready() -> None:
    try:
        from app.db.session import SessionLocal
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

    if bool(getattr(settings, "health_ready_check_s3", True)):
        try:
            s3 = get_s3_client()
            s3.head_bucket(Bucket=effective_bucket())
        except Exception as e:
            raise HTTPException(status_code=503, detail="s3 not ready") from e


# Готовность дёргает и docker-healthcheck, и внешний мониторинг. Без ограничения
# публичный адрес позволял бесплатно нагружать S3 и БД (каждый вызов — head_bucket).
@router.get("/health/ready")
def ready(_: object = rate_limit(key_prefix="health_ready", limit=240, window_seconds=60)):
    _check_ready()
    return {"status": "ready"}


@router.head("/health/ready", include_in_schema=False)
def ready_head(_: object = rate_limit(key_prefix="health_ready", limit=240, window_seconds=60)):
    _check_ready()
    return Response(status_code=200)


@router.post("/health/cron/admin-uploads-cleanup")
def cron_admin_uploads_cleanup(request: Request):
    """Старое имя cron-задачи: выполняет весь набор обслуживания хранилища.

    Набор задач один (`maintenance_schedule`), поэтому старый cron на сервере
    не «недоделывает» половину работы после обновления.
    """
    _require_cron_secret(request)
    return run_due_tasks()


@router.post("/health/cron/run-all")
def cron_run_all(request: Request):
    _require_cron_secret(request)
    return run_due_tasks()
