"""Ссылки для смены пароля: выпуск, гашение и уборка старых записей.

Публичная ручка `POST /auth/reset-password/confirm` и экран `/reset-password`
существовали, но токен никто не выпускал, поэтому «ссылка от администратора»
из подсказки была недостижима: администратор мог только продиктовать временный
пароль. Здесь выпуск ссылки и её обслуживание собраны в одном месте, чтобы
срок жизни, одноразовость и уборка не разъезжались между роутерами.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.password_reset import PasswordResetToken

log = logging.getLogger(__name__)

MIN_TTL_HOURS = 1
MAX_TTL_HOURS = 168  # неделя: дольше держать действующую ссылку опасно
DEFAULT_TTL_HOURS = 24
STALE_RETENTION_DAYS = 30


def hash_token(token: str) -> str:
    """В базе хранится только хеш: утечка таблицы не даёт действующих ссылок."""
    return hashlib.sha256(str(token or "").encode("utf-8", errors="ignore")).hexdigest()


def ttl_hours() -> int:
    raw = getattr(settings, "password_reset_link_ttl_hours", DEFAULT_TTL_HOURS) or DEFAULT_TTL_HOURS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TTL_HOURS
    return max(MIN_TTL_HOURS, min(MAX_TTL_HOURS, value))


def build_link(token: str) -> str:
    base = str(getattr(settings, "public_app_url", "") or "").strip().rstrip("/")
    path = f"/reset-password?token={token}"
    return f"{base}{path}" if base else path


def purge_stale(db: Session, *, now: datetime | None = None, days: int = STALE_RETENTION_DAYS) -> int:
    """Удалить использованные и просроченные ссылки старше `days` дней.

    Без этого каждая выдача ссылки или сброс пароля оставляли строку навсегда.
    Вызывается при выпуске новой ссылки: отдельный планировщик не нужен.
    """
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=max(1, int(days)))
    stale = or_(
        PasswordResetToken.used_at.is_not(None),
        PasswordResetToken.expires_at < moment,
    )
    result = db.execute(
        delete(PasswordResetToken).where(stale, PasswordResetToken.created_at < cutoff)
    )
    return int(getattr(result, "rowcount", 0) or 0)


def issue_token(
    db: Session,
    *,
    user_id: uuid.UUID,
    created_by_admin_id: uuid.UUID | None,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Выпустить новую ссылку и погасить прежние неиспользованные.

    Действующая ссылка всегда одна: если администратор нажал кнопку дважды,
    старая перестаёт работать, и в переписке не остаётся двух «верных» ссылок.
    """
    moment = now or datetime.now(timezone.utc)
    purge_stale(db, now=moment)

    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
        .values(used_at=moment)
        .execution_options(synchronize_session=False)
    )

    token = secrets.token_urlsafe(32)
    expires_at = moment + timedelta(hours=ttl_hours())
    db.add(
        PasswordResetToken(
            user_id=user_id,
            created_by_admin_id=created_by_admin_id,
            token_hash=hash_token(token),
            expires_at=expires_at,
            created_at=moment,
        )
    )
    db.flush()
    return token, expires_at


def find_active(db: Session, token: str) -> PasswordResetToken | None:
    row = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_token(token))
        .with_for_update()
    )
    return row
