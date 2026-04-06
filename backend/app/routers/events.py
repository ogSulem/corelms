from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limit
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.audit import LearningEvent, LearningEventType
from app.models.user import User
from app.services.skills import record_activity_and_award_xp


router = APIRouter(prefix="/events", tags=["events"])


class ExternalLinkClickRequest(BaseModel):
    url: str
    title: str | None = None
    source: str | None = None


@router.post("/external-link")
def external_link_click(
    request: Request,
    body: ExternalLinkClickRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: object = rate_limit(key_prefix="events_external_link", limit=240, window_seconds=60),
):
    url = str(body.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="missing url")

    title = str(body.title or "").strip() or None
    source = str(body.source or "").strip() or None

    record_activity_and_award_xp(db, user_id=str(user.id), xp=0)

    meta = json.dumps(
        {
            "action": "external_link",
            "url": url,
            "title": title,
            "source": source,
        },
        ensure_ascii=False,
    )
    db.add(
        LearningEvent(
            user_id=user.id,
            type=LearningEventType.submodule_opened,
            ref_id=None,
            meta=meta,
        )
    )
    db.commit()

    return {"ok": True}
