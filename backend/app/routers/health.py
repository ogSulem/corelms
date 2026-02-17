from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.redis_client import get_redis
from app.db.session import SessionLocal
from app.services.storage import get_s3_client
from app.core.config import settings

router = APIRouter(tags=["health"])


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
