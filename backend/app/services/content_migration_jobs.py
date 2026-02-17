from __future__ import annotations

from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.module import Submodule
from app.services.storage import ensure_bucket_exists, get_s3_client


def migrate_legacy_submodule_content_job(*, limit: int = 200) -> dict:
    take = max(1, min(int(limit or 200), 5000))

    ensure_bucket_exists()
    s3 = get_s3_client()

    db = SessionLocal()
    migrated = 0
    errors = 0

    try:
        rows = db.scalars(
            select(Submodule)
            .where(Submodule.content_object_key.is_(None))
            .where(Submodule.content != "")
            .order_by(Submodule.module_id, Submodule.order)
            .limit(take)
        ).all()

        for sub in rows:
            try:
                key = f"modules/{sub.module_id}/{int(sub.order):02d}/lesson.md"
                data = (sub.content or "").encode("utf-8")
                s3.put_object(
                    Bucket=settings.s3_bucket,
                    Key=key,
                    Body=data,
                    ContentType="text/markdown; charset=utf-8",
                )
                sub.content_object_key = key
                db.add(sub)
                migrated += 1
            except Exception:
                errors += 1
                continue

        db.commit()

        remaining_count = db.scalar(
            select(func.count(Submodule.id))
            .where(Submodule.content_object_key.is_(None))
            .where(Submodule.content != "")
        )
        remaining_count = int(remaining_count or 0)

        return {
            "ok": True,
            "migrated": int(migrated),
            "errors": int(errors),
            "limit": int(take),
            "remaining_count": remaining_count,
            "finished": remaining_count == 0,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
