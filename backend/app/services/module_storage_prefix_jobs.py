from __future__ import annotations

import re
import unicodedata

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.module import Module


def _slugify_s3_segment(v: str) -> str:
    s = str(v or "")
    try:
        s = unicodedata.normalize("NFKC", s)
    except Exception:
        pass
    s = s.strip()
    try:
        bad = ("Ã" in s) or ("Ð" in s) or ("Ñ" in s)
        if bad:
            try:
                fixed = s.encode("latin-1", errors="strict").decode("utf-8", errors="strict")
                if fixed and fixed != s:
                    s = fixed
            except Exception:
                pass
    except Exception:
        pass

    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s).strip()
    if s.endswith(".zip"):
        s = s[: -len(".zip")]
    s = re.sub(r"[^0-9a-zа-яё\-_. ]+", "-", s, flags=re.IGNORECASE)
    s = s.replace(" ", "-")
    s = re.sub(r"-+", "-", s).strip("-._")
    return (s[:80] or "module")


def backfill_module_storage_prefix_job(*, limit: int = 2000) -> dict:
    take = max(1, min(int(limit or 2000), 20000))

    db = SessionLocal()
    updated = 0
    errors = 0

    try:
        rows = db.scalars(
            select(Module)
            .where(Module.storage_prefix.is_(None))
            .order_by(Module.title)
            .limit(take)
        ).all()

        for m in rows:
            try:
                title = str(getattr(m, "title", "") or "").strip() or "module"
                safe = _slugify_s3_segment(title)
                pfx = f"modules/{safe}__{str(m.id)}/"
                m.storage_prefix = pfx
                db.add(m)
                updated += 1
            except Exception:
                errors += 1
                continue

        db.commit()

        remaining_count = db.scalar(select(func.count(Module.id)).where(Module.storage_prefix.is_(None)))
        remaining_count = int(remaining_count or 0)

        return {
            "ok": True,
            "updated": int(updated),
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
