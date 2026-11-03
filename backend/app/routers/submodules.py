from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limit
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.audit import LearningEvent, LearningEventType
from app.models.module import Submodule
from app.models.user import User
from app.services.skills import award_xp, record_activity_and_award_xp
from app.services.access import require_submodule_access
from app.services.learning import LearningService, read_meta_clause
from app.services.storage import get_s3_client
from app.core.config import settings

router = APIRouter(prefix="/submodules", tags=["submodules"])


LESSON_OPEN_WINDOW_SECONDS = 1800


def _should_record_open_event(*, user_id: object, submodule_id: object) -> bool:
    """Склеиваем повторные открытия одного урока окном (30 минут).

    Без Redis пишем событие как раньше: потеря истории хуже дубля.
    """
    try:
        from app.core.redis_client import get_redis

        redis = get_redis()
        key = f"lesson:open:{user_id}:{submodule_id}"
        if redis.get(key) is not None:
            return False
        redis.set(key, "1", ex=LESSON_OPEN_WINDOW_SECONDS)
        return True
    except Exception:
        return True


def _uuid(value: str, *, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid {field}") from e


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
    module = require_submodule_access(db, user, sub, lock=True)

    record_activity_and_award_xp(db, user_id=str(user.id), xp=0)
    # Одно открытие урока = одна запись в журнале. Интерфейс обращается к уроку
    # несколько раз (переход, возврат, перезагрузка вкладки), и раньше каждый
    # такой заход добавлял строку — журнал и «активность» заполнялись копиями.
    if _should_record_open_event(user_id=user.id, submodule_id=sub.id):
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
    module = require_submodule_access(db, user, sub, lock=False)

    from app.services.content import read_lesson_text
    content = read_lesson_text(sub.content, sub.content_object_key)

    return {
        "id": str(sub.id),
        "module_id": str(sub.module_id),
        "title": sub.title,
        "content": content,
        "content_mode": sub.content_mode,
        "presentation_mode": sub.presentation_mode,
        "primary_asset_id": str(sub.primary_asset_id) if sub.primary_asset_id else None,
        "order": int(sub.order),
        "quiz_id": str(sub.quiz_id),
        "requires_quiz": bool(getattr(sub, "requires_quiz", True)),
        "is_folder": bool(getattr(sub, "is_folder", False)),
        "outline_path": str(getattr(sub, "outline_path", None)) if getattr(sub, "outline_path", None) else None,
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
    module = require_submodule_access(db, user, sub, lock=True)

    record_activity_and_award_xp(db, user_id=str(user.id), xp=0)

    # Уже отмечено прочитанным? Спрашиваем базу точечно (метка — "read" или
    # JSON с action=read), а не выгружаем все открытия урока в память: после
    # сотни открытий эта выборка росла бесконечно.
    already_read = db.scalar(
        select(exists().where(
            LearningEvent.user_id == user.id,
            LearningEvent.type == LearningEventType.submodule_opened,
            LearningEvent.ref_id == sub.id,
            read_meta_clause(),
        ))
    )
    if already_read:
        LearningService(db).remember_completions(module, user)
        db.commit()
        return {"ok": True, "xp_awarded": 0}

    # Legacy compatibility: keep meta=="read" in addition to JSON.
    meta_value = "read"

    db.add(LearningEvent(user_id=user.id, type=LearningEventType.submodule_opened, ref_id=sub.id, meta=meta_value))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"ok": True, "xp_awarded": 0}

    award_xp(db, user_id=str(user.id), xp=5)
    LearningService(db).remember_completions(module, user)
    db.commit()
    return {"ok": True, "xp_awarded": 5}


@router.get("/{submodule_id}/read-status")
def read_status(submodule_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sid = _uuid(submodule_id, field="submodule_id")
    sub = db.get(Submodule, sid)
    if sub is None:
        raise HTTPException(404, "Материал не найден")
    require_submodule_access(db, user, sub)
    return {"read": bool(db.scalar(
        select(exists().where(
            LearningEvent.user_id == user.id,
            LearningEvent.type == LearningEventType.submodule_opened,
            LearningEvent.ref_id == sid,
            read_meta_clause(),
        ))
    ))}
