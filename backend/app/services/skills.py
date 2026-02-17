import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.audit import LearningEvent


def _recompute_level(xp: int) -> int:
    if xp < 0:
        xp = 0
    return (xp // 100) + 1


def _as_uuid(value) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except Exception:
        return None


def _apply_streak_on_activity(db: Session, *, user_id: str, now: datetime) -> None:
    from app.models.user import User

    uid = _as_uuid(user_id)
    if uid is None:
        return

    user = db.query(User).filter(User.id == uid).first()
    if user is None:
        return

    # Enterprise source of truth: users.last_activity_at
    # Fallback to learning_events for legacy rows.
    last_ts = user.last_activity_at
    if last_ts is None:
        last_event = (
            db.query(LearningEvent)
            .filter(LearningEvent.user_id == user.id)
            .order_by(LearningEvent.created_at.desc())
            .first()
        )
        last_ts = last_event.created_at if last_event is not None else None

    # If last_ts is None, it's their very first activity today.
    # In Taiga LMS, we award 1-day streak immediately on first activity.
    if last_ts is None:
        user.streak = 1
        user.last_activity_at = now
        return

    last_day = last_ts.date()
    today = now.date()
    if last_day == today:
        user.last_activity_at = now
        return
    if last_day == (today - timedelta(days=1)):
        user.streak = int(user.streak or 0) + 1
        user.last_activity_at = now
        return
    user.streak = 1
    user.last_activity_at = now


def award_xp(db: Session, *, user_id: str, xp: int) -> None:
    from app.models.user import User

    if xp == 0:
        return

    uid = _as_uuid(user_id)
    if uid is None:
        return

    user = db.query(User).filter(User.id == uid).first()
    if user is None:
        return

    user.xp = int(user.xp or 0) + int(xp)
    user.level = _recompute_level(int(user.xp or 0))


def record_activity_and_award_xp(db: Session, *, user_id: str, xp: int) -> None:
    now = datetime.now(timezone.utc)
    _apply_streak_on_activity(db, user_id=user_id, now=now)
    award_xp(db, user_id=user_id, xp=xp)
