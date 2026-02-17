import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.core.security_audit_log import audit_log
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: str
    name: str
    role: str
    position: str | None
    xp: int
    level: int
    streak: int
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str | None = None
    phone: str | None = None


class RegisterRequest(BaseModel):
    name: str
    position: str | None = None
    role: UserRole = UserRole.employee
    password: str


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def _create_access_token(*, user_id: str, role: str) -> str:
    now = datetime.utcnow()
    expire = now + timedelta(minutes=settings.jwt_access_token_minutes)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": expire,
        "iss": str(getattr(settings, "jwt_issuer", "corelms")),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _public_role(role: UserRole) -> str:
    if role == UserRole.admin:
        return "admin"
    return "user"


@router.post("/register", response_model=TokenResponse)
def register(
    request: Request,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    _: object = rate_limit(key_prefix="auth_register", limit=10, window_seconds=60),
):
    if not settings.allow_public_register:
        raise HTTPException(status_code=403, detail="registration disabled")

    if not payload.password or len(payload.password) < int(settings.password_min_length or 0):
        raise HTTPException(status_code=400, detail="password too short")

    existing = db.scalar(select(User).where(User.name == payload.name))
    if existing is not None:
        audit_log(db=db, request=request, event_type="auth_register_failed", meta={"reason": "user_exists", "username": payload.name})
        db.commit()
        raise HTTPException(status_code=409, detail="user already exists")

    user = User(
        name=payload.name,
        position=payload.position,
        role=UserRole.employee,
        xp=0,
        level=1,
        streak=0,
        password_hash=_hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit_log(db=db, request=request, event_type="auth_register_success", actor_user_id=user.id, target_user_id=user.id)
    db.commit()

    return TokenResponse(access_token=_create_access_token(user_id=str(user.id), role=_public_role(user.role)))


@router.post("/token", response_model=TokenResponse)
def token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    _: object = rate_limit(key_prefix="auth_token", limit=20, window_seconds=60),
):
    user = db.scalar(select(User).where(User.name == form_data.username))
    if user is None or not _verify_password(form_data.password, user.password_hash):
        audit_log(db=db, request=request, event_type="auth_login_failed", meta={"username": form_data.username})
        db.commit()
        raise HTTPException(status_code=401, detail="invalid credentials")

    audit_log(db=db, request=request, event_type="auth_login_success", actor_user_id=user.id, target_user_id=user.id)
    db.commit()

    return TokenResponse(access_token=_create_access_token(user_id=str(user.id), role=_public_role(user.role)))


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "name": user.name,
        "role": _public_role(user.role),
        "position": user.position,
        "xp": int(user.xp),
        "level": int(user.level),
        "streak": int(user.streak),
        "must_change_password": bool(getattr(user, "must_change_password", False)),
    }


@router.post("/change-password")
def change_password(
    request: Request,
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: object = rate_limit(key_prefix="auth_change_password", limit=10, window_seconds=60),
):
    if not body.current_password or not _verify_password(body.current_password, user.password_hash):
        audit_log(db=db, request=request, event_type="auth_change_password_failed", actor_user_id=user.id, target_user_id=user.id)
        db.commit()
        raise HTTPException(status_code=401, detail="invalid credentials")

    if not body.new_password or len(body.new_password) < int(settings.password_min_length or 0):
        raise HTTPException(status_code=400, detail="password too short")

    # Product rule: when admin issued a temporary password, enforce extra confirmation + phone collection.
    if bool(getattr(user, "must_change_password", False)):
        if str(body.confirm_password or "") != str(body.new_password or ""):
            raise HTTPException(status_code=400, detail="passwords do not match")

        phone = str(body.phone or "").strip()
        if not phone:
            raise HTTPException(status_code=400, detail="phone is required")
        # Minimal validation: keep digits and leading +, enforce sane length.
        norm = "+" + "".join([ch for ch in phone if ch.isdigit()]) if phone.startswith("+") else "".join([ch for ch in phone if ch.isdigit()])
        if len(norm) < 10 or len(norm) > 16:
            raise HTTPException(status_code=400, detail="invalid phone")
        user.phone = norm

    user.password_hash = _hash_password(body.new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.utcnow()
    db.add(user)
    audit_log(db=db, request=request, event_type="auth_change_password_success", actor_user_id=user.id, target_user_id=user.id)
    db.commit()
    return {"ok": True}
