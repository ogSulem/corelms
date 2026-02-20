from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limit
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.audit import LearningEvent, LearningEventType
from app.models.module import Submodule
from app.models.user import User
from app.services.skills import award_xp, record_activity_and_award_xp
from app.services.storage import get_s3_client
from app.core.config import settings

router = APIRouter(prefix="/submodules", tags=["submodules"])


def _uuid(value: str, *, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid {field}") from e


def _meta_action_is_read(meta: str | None) -> bool:
    if not meta:
        return False
    if str(meta).strip().lower() == "read":
        return True
    try:
        obj = json.loads(str(meta))
        if isinstance(obj, dict) and str(obj.get("action") or "").strip().lower() == "read":
            return True
    except Exception:
        return False
    return False


@router.post("/{submodule_id}/open")
def open_submodule(
    submodule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: object = rate_limit(key_prefix="submodule_open", limit=60, window_seconds=60),
):
    sid = _uuid(submodule_id, field="submodule_id")
    sub = db.scalar(select(Submodule).where(Submodule.id == sid))
    if sub is None:
        raise HTTPException(status_code=404, detail="submodule not found")

    record_activity_and_award_xp(db, user_id=str(user.id), xp=0)
    db.add(
        LearningEvent(
            user_id=user.id,
            type=LearningEventType.submodule_opened,
            ref_id=sub.id,
            meta=json.dumps({"action": "open"}, ensure_ascii=False),
        )
    )
    db.commit()

    return {"ok": True}


@router.get("/{submodule_id}")
def get_submodule(submodule_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sid = _uuid(submodule_id, field="submodule_id")
    sub = db.scalar(select(Submodule).where(Submodule.id == sid))
    if sub is None:
        raise HTTPException(status_code=404, detail="submodule not found")

    content = sub.content
    if sub.content_object_key:
        try:
            s3 = get_s3_client()
            obj = s3.get_object(Bucket=settings.s3_bucket, Key=sub.content_object_key)
            body = obj.get("Body")
            if body is not None:
                data = body.read()
                content = data.decode("utf-8", errors="ignore")
        except Exception:
            content = sub.content

    return {
        "id": str(sub.id),
        "module_id": str(sub.module_id),
        "title": sub.title,
        "content": content,
        "order": int(sub.order),
        "quiz_id": str(sub.quiz_id),
        "requires_quiz": bool(getattr(sub, "requires_quiz", True)),
    }


@router.post("/{submodule_id}/read")
def read_submodule(
    submodule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: object = rate_limit(key_prefix="submodule_read", limit=60, window_seconds=60),
):
    sid = _uuid(submodule_id, field="submodule_id")
    sub = db.scalar(select(Submodule).where(Submodule.id == sid))
    if sub is None:
        raise HTTPException(status_code=404, detail="submodule not found")

    record_activity_and_award_xp(db, user_id=str(user.id), xp=0)

    already_read = db.scalar(
        select(func.count(LearningEvent.id)).where(
            LearningEvent.user_id == user.id,
            LearningEvent.type == LearningEventType.submodule_opened,
            LearningEvent.ref_id == sub.id,
            LearningEvent.meta.is_not(None),
        )
    )
    if already_read and already_read > 0:
        # Soft check: if there is ANY read meta already, skip awarding XP.
        # We keep a separate query to preserve old meta=="read" semantics.
        existing = db.scalars(
            select(LearningEvent.meta)
            .where(
                LearningEvent.user_id == user.id,
                LearningEvent.type == LearningEventType.submodule_opened,
                LearningEvent.ref_id == sub.id,
                LearningEvent.meta.is_not(None),
            )
            .order_by(LearningEvent.created_at.desc())
            .limit(10)
        ).all()
        if any(_meta_action_is_read(m) for m in (existing or [])):
            return {"ok": True, "xp_awarded": 0}

    # Legacy compatibility: keep meta=="read" in addition to JSON.
    meta_value = json.dumps({"action": "read"}, ensure_ascii=False)

    db.add(LearningEvent(user_id=user.id, type=LearningEventType.submodule_opened, ref_id=sub.id, meta=meta_value))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"ok": True, "xp_awarded": 0}

    award_xp(db, user_id=str(user.id), xp=5)
    db.commit()
    return {"ok": True, "xp_awarded": 5}


@router.get("/{submodule_id}/read-status")
def read_status(submodule_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sid = _uuid(submodule_id, field="submodule_id")
    metas = db.scalars(
        select(LearningEvent.meta)
        .where(
            LearningEvent.user_id == user.id,
            LearningEvent.type == LearningEventType.submodule_opened,
            LearningEvent.ref_id == sid,
            LearningEvent.meta.is_not(None),
        )
        .order_by(LearningEvent.created_at.desc())
        .limit(20)
    ).all()
    return {"read": bool(any(_meta_action_is_read(m) for m in (metas or [])))}
