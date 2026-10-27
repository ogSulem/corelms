import uuid
import hashlib
import json
import ipaddress
from datetime import datetime, timezone
import re
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
from jose import jwt, JWTError
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.client_ip import client_ip_from_request
from app.core.rate_limit import rate_limit
from app.core.security_audit_log import audit_log
from app.core.security import get_current_user
from app.core.tokens import create_access_token, password_version
from app.services import auth_sessions
from app.services.app_settings import get_platform_settings
from app.db.session import get_db
from app.models.security_audit import SecurityAuditEvent
from app.models.user import User, UserRole
from app.models.password_reset import PasswordResetToken

router = APIRouter(prefix="/auth", tags=["auth"])

log = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    refresh_expires_in: int | None = None


class SessionItem(BaseModel):
    session_id: str
    created_at: str | None = None
    last_used_at: str | None = None
    expires_at: str | None = None
    ip: str | None = None
    ip_fp: str | None = None
    user_agent: str | None = None
    current: bool = False


class SessionsResponse(BaseModel):
    items: list[SessionItem]


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
    email: str | None = None
    position: str | None = None
    role: UserRole = UserRole.employee
    password: str


EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)


def _normalize_email(email: str | None) -> str | None:
    v = str(email or "").strip()
    if not v:
        return None
    v = v.lower()
    if not EMAIL_RE.fullmatch(v):
        raise HTTPException(status_code=400, detail="invalid email")
    return v


def _normalize_phone(phone: str | None) -> str | None:
    raw = str(phone or "").strip()
    if not raw:
        return None
    keep_plus = raw.startswith("+")
    digits = "".join([ch for ch in raw if ch.isdigit()])
    if not digits:
        raise HTTPException(status_code=400, detail="invalid phone")

    # Common RU normalization:
    # - 8XXXXXXXXXX -> +7XXXXXXXXXX
    # - 7XXXXXXXXXX -> +7XXXXXXXXXX
    # - XXXXXXXXXX  -> +7XXXXXXXXXX
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
        keep_plus = True
    elif len(digits) == 11 and digits.startswith("7"):
        keep_plus = True
    elif len(digits) == 10:
        digits = "7" + digits
        keep_plus = True

    out = ("+" + digits) if keep_plus else digits
    if len(digits) < 10 or len(digits) > 15:
        raise HTTPException(status_code=400, detail="invalid phone")
    return out


def _hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(422, "Пароль должен занимать не более 72 байт UTF-8")
    return pwd_context.hash(password)


def _verify_password(password: str, password_hash: str) -> bool:
    if len(password.encode("utf-8")) > 72:
        return False
    try:
        return pwd_context.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def _reset_token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8", errors="ignore")).hexdigest()


class ResetPasswordConfirmRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str | None = None


@router.post("/reset-password/confirm")
def reset_password_confirm(
    request: Request,
    body: ResetPasswordConfirmRequest,
    db: Session = Depends(get_db),
    _: object = rate_limit(key_prefix="auth_reset_password_confirm", limit=30, window_seconds=60),
):
    token_raw = str(body.token or "").strip()
    if not token_raw:
        raise HTTPException(status_code=400, detail="invalid token")

    if not body.new_password or len(body.new_password) < int(settings.password_min_length or 0):
        raise HTTPException(status_code=400, detail="password too short")

    if body.confirm_password is not None and str(body.confirm_password) != str(body.new_password):
        raise HTTPException(status_code=400, detail="passwords do not match")

    h = _reset_token_hash(token_raw)
    now = datetime.now(timezone.utc)

    prt = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == h).with_for_update())
    if prt is None:
        audit_log(db=db, request=request, event_type="auth_password_reset_failed", meta={"reason": "token_not_found"})
        db.commit()
        raise HTTPException(status_code=400, detail="invalid token")

    if getattr(prt, "used_at", None) is not None:
        audit_log(db=db, request=request, event_type="auth_password_reset_failed", actor_user_id=prt.user_id, target_user_id=prt.user_id, meta={"reason": "token_used"})
        db.commit()
        raise HTTPException(status_code=400, detail="invalid token")

    try:
        exp = getattr(prt, "expires_at", None)
        if exp is None or now.timestamp() >= auth_sessions.timestamp(exp):
            audit_log(db=db, request=request, event_type="auth_password_reset_failed", actor_user_id=prt.user_id, target_user_id=prt.user_id, meta={"reason": "token_expired"})
            db.commit()
            raise HTTPException(status_code=400, detail="token expired")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="invalid token")

    user = db.scalar(select(User).where(User.id == prt.user_id).with_for_update())
    if user is None:
        audit_log(db=db, request=request, event_type="auth_password_reset_failed", meta={"reason": "user_missing"})
        db.commit()
        raise HTTPException(status_code=400, detail="invalid token")

    user.password_hash = _hash_password(body.new_password)
    user.must_change_password = False
    user.password_changed_at = now
    db.add(user)

    db.execute(update(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)).values(used_at=now))

    audit_log(
        db=db,
        request=request,
        event_type="auth_password_reset_success",
        actor_user_id=user.id,
        target_user_id=user.id,
        meta={"token_id": str(prt.id)},
    )
    db.commit()

    # Password-version checks already invalidate all old JWTs and refreshes,
    # even if Redis is temporarily unavailable during this best-effort cleanup.
    try:
        auth_sessions.revoke_sessions(str(user.id), keep_password_version=password_version(user))
    except HTTPException:
        log.warning("Password reset session cleanup deferred")
    return {"ok": True}


def _public_role(role: UserRole) -> str:
    if role == UserRole.superadmin:
        return "superadmin"
    if role == UserRole.admin:
        return "admin"
    return "user"


def _client_ip_from_request(request: Request) -> str | None:
    return client_ip_from_request(request)


def _ip_fingerprint(ip: str | None) -> str | None:
    """Coarse IP fingerprint used for session/audit context.

    Goal: avoid treating small dynamic IP changes (e.g. last octet) as a new login context.
    """
    raw = str(ip or "").strip()
    if not raw:
        return None
    try:
        addr = ipaddress.ip_address(raw)
        if isinstance(addr, ipaddress.IPv4Address):
            # /24 fingerprint
            parts = raw.split(".")
            if len(parts) == 4:
                return ".".join(parts[:3] + ["0"]) + "/24"
            return str(addr) + "/32"
        # IPv6: keep first 4 hextets (roughly /64-ish human fingerprint)
        exploded = addr.exploded
        hextets = exploded.split(":")
        return ":".join(hextets[:4] + ["0000", "0000", "0000", "0000"]) + "/64"
    except Exception:
        return None


def _device_hash(*, user_agent: str, pepper: str | None = None) -> str:
    ua = str(user_agent or "").strip()
    p = str(pepper or "").strip()
    raw = (ua + "|" + p).encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def _try_parse_json(meta: str | None) -> dict | None:
    if not meta:
        return None
    try:
        obj = json.loads(str(meta))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _detect_new_login_context(*, db: Session, user_id, ip: str | None, device_hash: str) -> tuple[bool, bool]:
    # Heuristic: scan recent login success events and compare by device_hash and ip.
    # We keep it lightweight and resilient to legacy/non-JSON meta.
    rows = db.scalars(
        select(SecurityAuditEvent)
        .where(SecurityAuditEvent.target_user_id == user_id)
        .where(SecurityAuditEvent.event_type.in_(["auth_login_success", "auth_login_new_context"]))
        .order_by(SecurityAuditEvent.created_at.desc())
        .limit(50)
    ).all()

    seen_devices: set[str] = set()
    seen_ip_fps: set[str] = set()
    ip_fp = _ip_fingerprint(ip)
    for e in rows:
        m = _try_parse_json(e.meta)
        dh = str((m or {}).get("device_hash") or "").strip()
        if dh:
            seen_devices.add(dh)
        meta_ip_fp = str((m or {}).get("ip_fp") or "").strip()
        if meta_ip_fp:
            seen_ip_fps.add(meta_ip_fp)
        if e.ip:
            e_fp = _ip_fingerprint(str(e.ip))
            if e_fp:
                seen_ip_fps.add(e_fp)
        mip = str((m or {}).get("ip") or "").strip()
        if mip:
            mfp = _ip_fingerprint(mip)
            if mfp:
                seen_ip_fps.add(mfp)

    new_device = device_hash not in seen_devices if device_hash else False
    new_ip = (str(ip_fp).strip() not in seen_ip_fps) if ip_fp else False
    return new_device, new_ip


@router.post("/register", response_model=TokenResponse)
def register(
    request: Request,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    _: object = rate_limit(key_prefix="auth_register", limit=10, window_seconds=60),
):
    if not get_platform_settings(db).allow_public_register:
        raise HTTPException(status_code=403, detail="registration disabled")

    if not payload.password or len(payload.password) < int(settings.password_min_length or 0):
        raise HTTPException(status_code=400, detail="password too short")

    email_norm = _normalize_email(payload.email)

    if email_norm:
        existing_email = db.scalar(select(User).where(func.lower(User.email) == email_norm))
        if existing_email is not None:
            audit_log(db=db, request=request, event_type="auth_register_failed", meta={"reason": "email_exists", "email": email_norm})
            db.commit()
            raise HTTPException(status_code=409, detail="email already exists")

    user = User(
        name=payload.name,
        email=email_norm,
        position=payload.position,
        role=UserRole.employee,
        xp=0,
        level=1,
        streak=0,
        password_hash=_hash_password(payload.password),
    )
    verified_version = password_version(user)
    db.add(user)
    db.commit()
    db.refresh(user)

    audit_log(db=db, request=request, event_type="auth_register_success", actor_user_id=user.id, target_user_id=user.id)
    db.commit()

    refresh_token, refresh_ttl, sid = auth_sessions.issue_session(user, request, authenticated_password_version=verified_version)
    return TokenResponse(access_token=create_access_token(user, sid, authenticated_password_version=verified_version), refresh_token=refresh_token,
                         expires_in=settings.jwt_access_token_minutes * 60, refresh_expires_in=refresh_ttl)


@router.post("/token", response_model=TokenResponse)
def token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    _: object = rate_limit(key_prefix="auth_token", limit=20, window_seconds=60),
):
    login_raw = str(form_data.username or "").strip()
    login_norm = login_raw.lower()

    user = None
    if "@" in login_norm:
        user = db.scalar(select(User).where(func.lower(User.email) == login_norm))
    if user is None:
        # Name-based login is a compatibility mode. Names are not unique.
        # If the name is ambiguous, force login by email.
        matches = list(db.scalars(select(User).where(User.name == login_raw)).all())
        if len(matches) == 1:
            user = matches[0]
        elif len(matches) > 1:
            audit_log(db=db, request=request, event_type="auth_login_failed", meta={"username": form_data.username, "reason": "ambiguous_name"})
            db.commit()
            raise HTTPException(status_code=400, detail="ambiguous login; use email")
    if user is None or not _verify_password(form_data.password, user.password_hash):
        audit_log(db=db, request=request, event_type="auth_login_failed", meta={"username": form_data.username})
        db.commit()
        raise HTTPException(status_code=401, detail="invalid credentials")

    # Capture exactly the password that was verified, before commit expires the
    # ORM object. A simultaneous admin reset must not authenticate the old password.
    verified_version = password_version(user)
    ip = _client_ip_from_request(request)
    ip_fp = _ip_fingerprint(ip)
    ua = str(request.headers.get("user-agent") or "").strip()
    dh = _device_hash(user_agent=ua, pepper=str(getattr(settings, "jwt_secret_key", "") or ""))
    new_device, new_ip = _detect_new_login_context(db=db, user_id=user.id, ip=ip, device_hash=dh)

    audit_log(
        db=db,
        request=request,
        event_type="auth_login_success",
        actor_user_id=user.id,
        target_user_id=user.id,
        meta={"ip": ip, "ip_fp": ip_fp, "user_agent": ua, "device_hash": dh},
    )

    if new_device or new_ip:
        audit_log(
            db=db,
            request=request,
            event_type="auth_login_new_context",
            actor_user_id=user.id,
            target_user_id=user.id,
            meta={
                "ip": ip,
                "ip_fp": ip_fp,
                "user_agent": ua,
                "device_hash": dh,
                "new_device": bool(new_device),
                "new_ip": bool(new_ip),
            },
        )

    db.commit()

    # Every explicit login is independent, even on two identical browsers.
    refresh_token, refresh_ttl, sid = auth_sessions.issue_session(user, request, authenticated_password_version=verified_version)
    return TokenResponse(access_token=create_access_token(user, sid, authenticated_password_version=verified_version), refresh_token=refresh_token,
                         expires_in=settings.jwt_access_token_minutes * 60, refresh_expires_in=refresh_ttl)


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


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    request: Request,
    db: Session = Depends(get_db),
    _: object = rate_limit(key_prefix="auth_refresh", limit=120, window_seconds=60),
):
    auth = str(request.headers.get("authorization") or "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")

    session = auth_sessions.resolve_refresh(token)
    if session is None:
        raise HTTPException(401, "invalid token")
    try:
        user = db.get(User, uuid.UUID(session["user_id"]))
    except (ValueError, KeyError):
        user = None
    if user is None:
        raise HTTPException(401, "invalid token")
    rotated = auth_sessions.rotate_session(token, user, request)
    if rotated is None:
        # The same device may have just changed its password in another tab.
        # Re-read SQL once; never recreate a revoked SID or accept an old password.
        user = db.scalar(select(User).where(User.id == user.id).execution_options(populate_existing=True))
        rotated = auth_sessions.rotate_session(token, user, request) if user else None
    if rotated is None:
        raise HTTPException(401, "invalid token")
    new_refresh, refresh_ttl, sid = rotated
    token_out = create_access_token(user, sid)
    audit_log(
        db=db,
        request=request,
        event_type="auth_refresh",
        actor_user_id=user.id,
        target_user_id=user.id,
        meta={
            "ip": _client_ip_from_request(request),
            "ip_fp": _ip_fingerprint(_client_ip_from_request(request)),
            "user_agent": str(request.headers.get("user-agent") or "")[:400],
        },
    )
    db.commit()
    return TokenResponse(
        access_token=token_out,
        refresh_token=new_refresh,
        expires_in=settings.jwt_access_token_minutes * 60,
        refresh_expires_in=int(refresh_ttl),
    )


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
    _: object = rate_limit(key_prefix="auth_logout", limit=120, window_seconds=60),
):
    auth = str(request.headers.get("authorization") or "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    session = auth_sessions.resolve_refresh(token) if token else None
    if session is None:
        # If a refresh response rotated a cookie that this tab never received,
        # the signed access cookie still identifies the stable session to revoke.
        access = request.cookies.get("core_token") or (token if not token.startswith("rt_") else "")
        if access:
            try:
                payload = jwt.decode(access, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm],
                                     issuer=settings.jwt_issuer, options={"verify_exp": False})
                user = db.get(User, uuid.UUID(payload["sub"]))
                candidate = auth_sessions.get_session(str(payload.get("sid") or ""))
                if user and candidate and candidate["user_id"] == str(user.id) and candidate.get("password_version") == payload.get("pv") == password_version(user):
                    session = candidate
            except (JWTError, KeyError, ValueError, TypeError):
                pass
    if session:
        auth_sessions.revoke_sessions(session["user_id"], only_sid=session["sid"])
        audit_log(db=db, request=request, event_type="auth_logout", actor_user_id=uuid.UUID(session["user_id"]))
        db.commit()
    return {"ok": True}


@router.get("/sessions", response_model=SessionsResponse)
def list_sessions(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    current_sid = getattr(request.state, "session_id", None)
    return {"items": [SessionItem(session_id=session["sid"], created_at=session.get("created_at"),
        last_used_at=session.get("last_used_at"), expires_at=session.get("expires_at"),
        ip=session.get("ip"), user_agent=session.get("user_agent"), current=session["sid"] == current_sid)
        for session in auth_sessions.list_sessions(str(user.id)) if auth_sessions.session_matches_password(session, user)]}


class RevokeSessionRequest(BaseModel):
    session_id: uuid.UUID


@router.post("/sessions/revoke")
def revoke_session(request: Request, body: RevokeSessionRequest, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    count = auth_sessions.revoke_sessions(str(user.id), only_sid=str(body.session_id))
    audit_log(db=db, request=request, event_type="auth_session_revoked", actor_user_id=user.id,
              meta={"session_id": str(body.session_id), "count": count})
    db.commit()
    return {"ok": True}


@router.post("/sessions/revoke-all")
def revoke_all_sessions(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = auth_sessions.revoke_sessions(str(user.id))
    audit_log(db=db, request=request, event_type="auth_session_revoked_all", actor_user_id=user.id, meta={"count": count})
    db.commit()
    return {"ok": True}


@router.post("/sessions/revoke-others")
def revoke_other_sessions(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sid = getattr(request.state, "session_id", None)
    if not sid:
        raise HTTPException(409, "Обновите страницу, чтобы определить текущую сессию")
    count = auth_sessions.revoke_sessions(str(user.id), keep_sid=sid)
    audit_log(db=db, request=request, event_type="auth_session_revoked_others", actor_user_id=user.id, meta={"count": count})
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(
    request: Request,
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: object = rate_limit(key_prefix="auth_change_password", limit=10, window_seconds=60),
):
    user = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not body.current_password or not _verify_password(body.current_password, user.password_hash):
        audit_log(db=db, request=request, event_type="auth_change_password_failed", actor_user_id=user.id, target_user_id=user.id)
        db.commit()
        raise HTTPException(status_code=400, detail="Текущий пароль неверен")

    if not body.new_password or len(body.new_password) < int(settings.password_min_length or 0):
        raise HTTPException(status_code=400, detail="password too short")

    if body.confirm_password is not None and body.confirm_password != body.new_password:
        raise HTTPException(422, "Пароли не совпадают")
    if _verify_password(body.new_password, user.password_hash):
        raise HTTPException(422, "Новый пароль должен отличаться от текущего")

    # Product rule: when admin issued a temporary password, enforce extra confirmation + phone collection.
    if bool(getattr(user, "must_change_password", False)):
        if str(body.confirm_password or "") != str(body.new_password or ""):
            raise HTTPException(status_code=400, detail="passwords do not match")

        norm_phone = _normalize_phone(body.phone)
        if not norm_phone:
            raise HTTPException(status_code=400, detail="phone is required")
        user.phone = norm_phone
    else:
        # Optional phone collection on regular password change.
        norm_phone = _normalize_phone(body.phone)
        if norm_phone:
            user.phone = norm_phone

    user.password_hash = _hash_password(body.new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.now(timezone.utc)
    changed_version = password_version(user)
    db.add(user)
    audit_log(db=db, request=request, event_type="auth_change_password_success", actor_user_id=user.id, target_user_id=user.id)
    db.commit()

    try:
        auth_sessions.revoke_sessions(str(user.id), keep_sid=getattr(request.state, "session_id", None),
                                      new_password_version=changed_version, keep_password_version=changed_version)
    except HTTPException:
        # The password was saved; do not report failure or recreate a lost SID.
        # Old credentials are rejected by their password version on every request.
        log.warning("Password changed; current session could not be preserved")
        return {"ok": True, "reauthenticate": True}
    return {"ok": True}
