from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User, UserRole


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
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

    try:
        request.state.user_id = str(user.id)
    except Exception:
        pass
    return user


def require_roles(*roles: UserRole):
    def _dep(user: User = Depends(get_current_user)) -> User:
        # Role model: admin + employee
        # - admin can access everything
        # - employee can access only endpoints that explicitly allow it
        if user.role == UserRole.admin:
            return user

        if user.role not in roles:
            raise HTTPException(status_code=403, detail="forbidden")
        return user

    return _dep
