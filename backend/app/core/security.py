from __future__ import annotations

import hmac
import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User, UserRole
from app.core.tokens import password_version
from app.services.auth_sessions import get_session


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def require_cron_secret(request: Request) -> None:
    secret = str(getattr(settings, "cron_secret", "") or "").strip()
    if not secret:
        raise HTTPException(status_code=404, detail="not found")

    provided = str(request.headers.get("x-cron-secret") or "").strip()
    if not provided or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=403, detail="forbidden")


def _resolve_user(request: Request, db: Session, token: str) -> User:
    """Проверить токен и вернуть пользователя. Общая часть обычных и потоковых запросов."""
    if not token:
        token = request.cookies.get("core_token")
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=str(getattr(settings, "jwt_issuer", "corelms")),
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="invalid token")
    except JWTError as e:
        raise HTTPException(status_code=401, detail="invalid token") from e

    try:
        user_id = uuid.UUID(str(user_id))
    except ValueError as e:
        raise HTTPException(status_code=401, detail="invalid token") from e

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="invalid token")

    # Old access tokens refresh once into the SID-bound format at rollout.
    sid = payload.get("sid")
    if not sid or payload.get("pv") != password_version(user):
        raise HTTPException(401, "invalid token")
    session = get_session(str(sid))
    if not session or session.get("user_id") != str(user.id) or session.get("password_version") != payload.get("pv"):
        raise HTTPException(401, "session revoked")
    request.state.user_id = str(user.id)
    request.state.session_id = str(sid)
    if user.must_change_password and request.url.path not in {"/auth/me", "/auth/change-password", "/auth/sessions", "/auth/sessions/revoke-all"}:
        raise HTTPException(403, {"error_code": "password_change_required", "error_message": "Сначала смените временный пароль"})
    return user


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    return _resolve_user(request, db, token)


def _token_from(request: Request, token: str) -> str:
    return token or str(request.cookies.get("core_token") or "")


def get_current_user_stream(
    request: Request,
    token: str = Depends(oauth2_scheme),
) -> User:
    """Для SSE-потоков: соединение с БД нужно только на время проверки.

    Обычная зависимость держит сессию до конца ответа, а поток живёт минутами
    и часами — несколько открытых вкладок исчерпывали пул, и любой другой
    запрос падал с 500. Здесь сессия закрывается сразу после авторизации.
    """
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        user = _resolve_user(request, db, _token_from(request, token))
        db.expunge(user)
        return user
    finally:
        db.close()


def require_roles_stream(*roles: UserRole):
    """То же, что require_roles, но для долгих SSE-потоков."""

    def _dep(user: User = Depends(get_current_user_stream)) -> User:
        if user.role == UserRole.superadmin:
            return user
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="forbidden")
        return user

    return _dep


def require_roles(*roles: UserRole):
    def _dep(user: User = Depends(get_current_user)) -> User:
        # Admin is not a superadmin. Only the top role inherits all permissions.
        if user.role == UserRole.superadmin:
            return user

        if user.role not in roles:
            raise HTTPException(status_code=403, detail="forbidden")
        return user

    return _dep
