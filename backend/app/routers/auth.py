import uuid
import hashlib
import json
import ipaddress
from datetime import datetime, timedelta
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.client_ip import client_ip_from_request
from app.core.rate_limit import rate_limit
from app.core.security_audit_log import audit_log
from app.core.security import get_current_user
from app.core.redis_client import get_redis
from app.db.session import get_db
from app.models.security_audit import SecurityAuditEvent
from app.models.user import User, UserRole
from app.models.password_reset import PasswordResetToken

router = APIRouter(prefix="/auth", tags=["auth"])

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
    return pwd_context.hash(password)


def _verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


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
    now = datetime.utcnow()

    prt = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == h))
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
        if exp is None or now >= exp:
            audit_log(db=db, request=request, event_type="auth_password_reset_failed", actor_user_id=prt.user_id, target_user_id=prt.user_id, meta={"reason": "token_expired"})
            db.commit()
            raise HTTPException(status_code=400, detail="token expired")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="invalid token")

    user = db.scalar(select(User).where(User.id == prt.user_id))
    if user is None:
        audit_log(db=db, request=request, event_type="auth_password_reset_failed", meta={"reason": "user_missing"})
        db.commit()
        raise HTTPException(status_code=400, detail="invalid token")

    user.password_hash = _hash_password(body.new_password)
    user.must_change_password = False
    user.password_changed_at = now
    db.add(user)

    prt.used_at = now
    db.add(prt)

    audit_log(
        db=db,
        request=request,
        event_type="auth_password_reset_success",
        actor_user_id=user.id,
        target_user_id=user.id,
        meta={"token_id": str(prt.id)},
    )
    db.commit()

    return {"ok": True}


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


def _now() -> datetime:
    return datetime.utcnow()


def _refresh_token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8", errors="ignore")).hexdigest()


def _user_sessions_key(user_id: str) -> str:
    return f"auth:user_sessions:{str(user_id)}"


def _user_device_session_key(*, user_id: str, device_hash: str) -> str:
    return f"auth:user_device_session:{str(user_id)}:{str(device_hash)}"


def _session_id_from_hash(h: str) -> str:
    v = str(h or "").strip()
    if not v:
        return ""
    return v[:12]


def _session_limits() -> tuple[int, int, int]:
    # Returns: refresh_ttl_seconds, idle_ttl_seconds, absolute_ttl_seconds
    refresh_days = int(getattr(settings, "session_refresh_token_days", 30) or 30)
    idle_hours = int(getattr(settings, "session_idle_timeout_hours", 12) or 12)
    abs_days = int(getattr(settings, "session_absolute_timeout_days", 30) or 30)
    refresh_ttl = max(60 * 60, refresh_days * 24 * 60 * 60)
    idle_ttl = max(5 * 60, idle_hours * 60 * 60)
    abs_ttl = max(60 * 60, abs_days * 24 * 60 * 60)
    return refresh_ttl, idle_ttl, abs_ttl


def _issue_refresh_session(*, user: User, request: Request) -> tuple[str, int]:
    token = "rt_" + str(uuid.uuid4()) + "_" + str(uuid.uuid4())
    h = _refresh_token_hash(token)
    refresh_ttl, idle_ttl, abs_ttl = _session_limits()
    now = _now()
    ip = _client_ip_from_request(request)
    ip_fp = _ip_fingerprint(ip)
    ua = str(request.headers.get("user-agent") or "")[:400]
    dh = _device_hash(user_agent=ua, pepper=str(getattr(settings, "jwt_secret_key", "") or ""))
    payload = {
        "sid": str(uuid.uuid4()),
        "user_id": str(user.id),
        "created_at": now.isoformat(),
        "last_used_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=abs_ttl)).isoformat(),
        "idle_ttl_seconds": int(idle_ttl),
        "ip": ip,
        "ip_fp": ip_fp,
        "user_agent": ua,
        "device_hash": dh,
    }
    r = get_redis()
    r.setex(f"auth:refresh:{h}", int(refresh_ttl), json.dumps(payload, ensure_ascii=False))
    r.sadd(_user_sessions_key(str(user.id)), h)
    r.expire(_user_sessions_key(str(user.id)), int(refresh_ttl))
    if dh:
        r.setex(_user_device_session_key(user_id=str(user.id), device_hash=dh), int(refresh_ttl), str(h))
    return token, refresh_ttl


def _rotate_refresh_session_by_hash(*, refresh_hash: str, request: Request) -> tuple[str, str, int, dict, str, str] | None:
    h = str(refresh_hash or "").strip()
    if not h:
        return None
    r = get_redis()
    raw = r.get(f"auth:refresh:{h}")
    if not raw:
        # Grace window: another request may have already rotated this refresh token.
        # This happens on fast reloads where multiple refresh calls race.
        try:
            rot = r.get(f"auth:refresh_rot:{h}")
            if rot:
                payload = json.loads(str(rot))
                next_token = str(payload.get("token") or "").strip()
                next_h = str(payload.get("hash") or "").strip()
                if next_token and next_h:
                    raw2 = r.get(f"auth:refresh:{next_h}")
                    if raw2:
                        sess2 = json.loads(str(raw2))
                        if isinstance(sess2, dict):
                            uid2 = str(sess2.get("user_id") or "").strip()
                            ttl2 = r.ttl(f"auth:refresh:{next_h}")
                            try:
                                refresh_ttl2 = int(ttl2) if ttl2 and int(ttl2) > 0 else int(_session_limits()[0])
                            except Exception:
                                refresh_ttl2 = int(_session_limits()[0])
                            return next_token, uid2, refresh_ttl2, sess2, h, next_h
        except Exception:
            pass
        return None
    try:
        sess = json.loads(str(raw))
        if not isinstance(sess, dict):
            return None
    except Exception:
        return None

    now = _now()
    try:
        last_used = datetime.fromisoformat(str(sess.get("last_used_at") or ""))
    except Exception:
        last_used = now
    try:
        expires_at = datetime.fromisoformat(str(sess.get("expires_at") or ""))
    except Exception:
        expires_at = now

    idle_ttl = int(sess.get("idle_ttl_seconds") or 0)
    if idle_ttl <= 0:
        _, idle_ttl, _ = _session_limits()

    if now >= expires_at:
        r.delete(f"auth:refresh:{h}")
        return None
    if (now - last_used).total_seconds() > float(idle_ttl):
        r.delete(f"auth:refresh:{h}")
        return None

    new_token = "rt_" + str(uuid.uuid4()) + "_" + str(uuid.uuid4())
    new_h = _refresh_token_hash(new_token)
    refresh_ttl, _, _ = _session_limits()
    ip = _client_ip_from_request(request)
    ip_fp = _ip_fingerprint(ip)
    ua = str(request.headers.get("user-agent") or "")[:400]

    sess["last_used_at"] = now.isoformat()
    sess["ip"] = ip
    sess["ip_fp"] = ip_fp
    sess["user_agent"] = ua
    if not str(sess.get("device_hash") or "").strip():
        sess["device_hash"] = _device_hash(user_agent=ua, pepper=str(getattr(settings, "jwt_secret_key", "") or ""))
    if not str(sess.get("sid") or "").strip():
        sess["sid"] = str(uuid.uuid4())

    r.setex(f"auth:refresh:{new_h}", int(refresh_ttl), json.dumps(sess, ensure_ascii=False))
    # Grace window mapping for concurrent refresh attempts with the same old token.
    try:
        r.setex(
            f"auth:refresh_rot:{h}",
            10,
            json.dumps({"token": new_token, "hash": new_h}, ensure_ascii=False),
        )
    except Exception:
        pass
    r.delete(f"auth:refresh:{h}")

    uid = str(sess.get("user_id") or "").strip()
    if uid:
        key = _user_sessions_key(uid)
        r.srem(key, h)
        r.sadd(key, new_h)
        r.expire(key, int(refresh_ttl))
        dh = str(sess.get("device_hash") or "").strip()
        if dh:
            r.setex(_user_device_session_key(user_id=uid, device_hash=dh), int(refresh_ttl), str(new_h))

    return new_token, uid, refresh_ttl, sess, h, new_h


def _rotate_refresh_session(*, refresh_token: str, request: Request) -> tuple[str, str, int, dict, str, str] | None:
    tok = str(refresh_token or "").strip()
    if not tok:
        return None
    h = _refresh_token_hash(tok)
    r = get_redis()
    raw = r.get(f"auth:refresh:{h}")
    if not raw:
        # Grace window: another request may have already rotated this refresh token.
        try:
            rot = r.get(f"auth:refresh_rot:{h}")
            if rot:
                payload = json.loads(str(rot))
                next_token = str(payload.get("token") or "").strip()
                next_h = str(payload.get("hash") or "").strip()
                if next_token and next_h:
                    raw2 = r.get(f"auth:refresh:{next_h}")
                    if raw2:
                        sess2 = json.loads(str(raw2))
                        if isinstance(sess2, dict):
                            uid2 = str(sess2.get("user_id") or "").strip()
                            ttl2 = r.ttl(f"auth:refresh:{next_h}")
                            try:
                                refresh_ttl2 = int(ttl2) if ttl2 and int(ttl2) > 0 else int(_session_limits()[0])
                            except Exception:
                                refresh_ttl2 = int(_session_limits()[0])
                            return next_token, uid2, refresh_ttl2, sess2, h, next_h
        except Exception:
            pass
        return None
    try:
        sess = json.loads(str(raw))
        if not isinstance(sess, dict):
            return None
    except Exception:
        return None

    now = _now()
    try:
        created_at = datetime.fromisoformat(str(sess.get("created_at") or ""))
    except Exception:
        created_at = now
    try:
        last_used = datetime.fromisoformat(str(sess.get("last_used_at") or ""))
    except Exception:
        last_used = created_at
    try:
        expires_at = datetime.fromisoformat(str(sess.get("expires_at") or ""))
    except Exception:
        expires_at = now

    idle_ttl = int(sess.get("idle_ttl_seconds") or 0)
    if idle_ttl <= 0:
        _, idle_ttl, _ = _session_limits()

    # Enforce absolute + idle expiration.
    if now >= expires_at:
        r.delete(f"auth:refresh:{h}")
        return None
    if (now - last_used).total_seconds() > float(idle_ttl):
        r.delete(f"auth:refresh:{h}")
        return None

    # Rotate token.
    new_token = "rt_" + str(uuid.uuid4()) + "_" + str(uuid.uuid4())
    new_h = _refresh_token_hash(new_token)
    refresh_ttl, _, _ = _session_limits()
    ip = _client_ip_from_request(request)
    ip_fp = _ip_fingerprint(ip)
    ua = str(request.headers.get("user-agent") or "")[:400]
    sess["last_used_at"] = now.isoformat()
    sess["ip"] = ip
    sess["ip_fp"] = ip_fp
    sess["user_agent"] = ua
    if not str(sess.get("sid") or "").strip():
        sess["sid"] = str(uuid.uuid4())
    if not str(sess.get("device_hash") or "").strip():
        sess["device_hash"] = _device_hash(user_agent=ua, pepper=str(getattr(settings, "jwt_secret_key", "") or ""))
    r.setex(f"auth:refresh:{new_h}", int(refresh_ttl), json.dumps(sess, ensure_ascii=False))
    # Grace window mapping for concurrent refresh attempts with the same old token.
    try:
        r.setex(
            f"auth:refresh_rot:{h}",
            10,
            json.dumps({"token": new_token, "hash": new_h}, ensure_ascii=False),
        )
    except Exception:
        pass
    r.delete(f"auth:refresh:{h}")

    uid = str(sess.get("user_id") or "").strip()
    if uid:
        key = _user_sessions_key(uid)
        r.srem(key, h)
        r.sadd(key, new_h)
        r.expire(key, int(refresh_ttl))
        dh = str(sess.get("device_hash") or "").strip()
        if dh:
            r.setex(_user_device_session_key(user_id=uid, device_hash=dh), int(refresh_ttl), str(new_h))

    return new_token, uid, refresh_ttl, sess, h, new_h


def _public_role(role: UserRole) -> str:
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
    if not settings.allow_public_register:
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
    db.add(user)
    db.commit()
    db.refresh(user)

    audit_log(db=db, request=request, event_type="auth_register_success", actor_user_id=user.id, target_user_id=user.id)
    db.commit()

    expires_in = None
    try:
        expires_in = int(settings.jwt_access_token_minutes) * 60
    except Exception:
        expires_in = None

    return TokenResponse(
        access_token=_create_access_token(user_id=str(user.id), role=_public_role(user.role)),
        expires_in=expires_in,
    )


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

    refresh_token = ""
    refresh_ttl = 0
    try:
        r = get_redis()
        existing_h = str(r.get(_user_device_session_key(user_id=str(user.id), device_hash=dh)) or "").strip()
        rotated = _rotate_refresh_session_by_hash(refresh_hash=existing_h, request=request) if existing_h else None
        if rotated is not None:
            refresh_token, _uid, refresh_ttl, _sess, _old_h, _new_h = rotated
        else:
            refresh_token, refresh_ttl = _issue_refresh_session(user=user, request=request)
    except Exception:
        refresh_token, refresh_ttl = _issue_refresh_session(user=user, request=request)

    expires_in = None
    try:
        expires_in = int(settings.jwt_access_token_minutes) * 60
    except Exception:
        expires_in = None

    return TokenResponse(
        access_token=_create_access_token(user_id=str(user.id), role=_public_role(user.role)),
        refresh_token=refresh_token,
        expires_in=expires_in,
        refresh_expires_in=int(refresh_ttl),
    )


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

    rotated = _rotate_refresh_session(refresh_token=token, request=request)
    if rotated is None:
        raise HTTPException(status_code=401, detail="invalid token")
    new_refresh, user_id, refresh_ttl, _sess, _old_h, _new_h = rotated
    try:
        uid = uuid.UUID(str(user_id))
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    user = db.scalar(select(User).where(User.id == uid))
    if user is None:
        raise HTTPException(status_code=401, detail="invalid token")

    expires_in = None
    try:
        expires_in = int(settings.jwt_access_token_minutes) * 60
    except Exception:
        expires_in = None

    token_out = _create_access_token(user_id=str(user.id), role=_public_role(user.role))
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
        expires_in=expires_in,
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
    if token:
        try:
            h = _refresh_token_hash(token)
            r = get_redis()
            raw = r.get(f"auth:refresh:{h}")
            r.delete(f"auth:refresh:{h}")
            uid = None
            try:
                sess = json.loads(str(raw)) if raw else None
                if isinstance(sess, dict):
                    uid = sess.get("user_id")
            except Exception:
                uid = None
            if uid:
                try:
                    r.srem(_user_sessions_key(str(uid)), h)
                except Exception:
                    pass
                audit_log(db=db, request=request, event_type="auth_logout", actor_user_id=uuid.UUID(str(uid)), target_user_id=uuid.UUID(str(uid)))
                db.commit()
        except Exception:
            pass
    return {"ok": True}


@router.get("/sessions", response_model=SessionsResponse)
def list_sessions(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    r = get_redis()
    key = _user_sessions_key(str(user.id))
    hashes = [str(x) for x in (r.smembers(key) or set())]
    items: list[SessionItem] = []

    current_h = ""
    current_sid = ""
    try:
        # Frontend stores refresh token in httpOnly cookie. Authorization typically holds the access token.
        tok = str(request.cookies.get("core_refresh") or "").strip()
        if not tok:
            auth = str(request.headers.get("authorization") or "")
            if auth.lower().startswith("bearer "):
                tok = auth.split(" ", 1)[1].strip()
        if tok:
            current_h = _refresh_token_hash(tok)
            raw0 = r.get(f"auth:refresh:{current_h}")
            if raw0:
                try:
                    sess0 = json.loads(str(raw0))
                    if isinstance(sess0, dict):
                        current_sid = str(sess0.get("sid") or "").strip()
                except Exception:
                    current_sid = ""
    except Exception:
        current_h = ""
        current_sid = ""

    alive_hashes: list[str] = []
    for h in hashes:
        raw = r.get(f"auth:refresh:{h}")
        if not raw:
            continue
        try:
            sess = json.loads(str(raw))
        except Exception:
            continue
        if not isinstance(sess, dict):
            continue
        if str(sess.get("user_id") or "") != str(user.id):
            continue
        alive_hashes.append(h)
        sid = str(sess.get("sid") or "").strip()
        items.append(
            SessionItem(
                session_id=(sid or _session_id_from_hash(h)),
                created_at=str(sess.get("created_at") or "") or None,
                last_used_at=str(sess.get("last_used_at") or "") or None,
                expires_at=str(sess.get("expires_at") or "") or None,
                ip=str(sess.get("ip") or "") or None,
                ip_fp=str(sess.get("ip_fp") or "") or None,
                user_agent=str(sess.get("user_agent") or "") or None,
                current=bool((current_sid and sid and sid == current_sid) or (not current_sid and current_h and h == current_h)),
            )
        )

    if len(alive_hashes) != len(hashes):
        try:
            stale = [h for h in hashes if h not in set(alive_hashes)]
            if stale:
                r.srem(key, *stale)
        except Exception:
            pass

    items.sort(key=lambda x: str(x.last_used_at or ""), reverse=True)
    return {"items": items}


class RevokeSessionRequest(BaseModel):
    session_id: str


@router.post("/sessions/revoke")
def revoke_session(
    request: Request,
    body: RevokeSessionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sid = str(body.session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="invalid session_id")
    r = get_redis()
    key = _user_sessions_key(str(user.id))
    hashes = [str(x) for x in (r.smembers(key) or set())]
    target: str | None = None
    for h in hashes:
        raw = r.get(f"auth:refresh:{h}")
        if raw:
            try:
                sess = json.loads(str(raw))
                if isinstance(sess, dict) and str(sess.get("sid") or "").strip() == sid:
                    target = h
                    break
            except Exception:
                pass
        if _session_id_from_hash(h) == sid:
            target = h
            break
    if not target:
        return {"ok": True}
    try:
        raw = r.get(f"auth:refresh:{target}")
        sess = json.loads(str(raw)) if raw else None
        if isinstance(sess, dict):
            dh = str(sess.get("device_hash") or "").strip()
            if dh:
                dk = _user_device_session_key(user_id=str(user.id), device_hash=dh)
                if str(r.get(dk) or "").strip() == str(target):
                    r.delete(dk)
    except Exception:
        pass
    r.delete(f"auth:refresh:{target}")
    r.srem(key, target)
    audit_log(db=db, request=request, event_type="auth_session_revoked", actor_user_id=user.id, target_user_id=user.id, meta={"session_id": sid})
    db.commit()
    return {"ok": True}


@router.post("/sessions/revoke-all")
def revoke_all_sessions(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    r = get_redis()
    key = _user_sessions_key(str(user.id))
    hashes = [str(x) for x in (r.smembers(key) or set())]
    revoked: list[str] = []
    for h in hashes:
        r.delete(f"auth:refresh:{h}")
        revoked.append(h)
    if revoked:
        try:
            r.srem(key, *revoked)
        except Exception:
            pass
    try:
        # Best-effort cleanup of device mappings.
        pattern = f"auth:user_device_session:{str(user.id)}:*"
        keys = [k for k in r.scan_iter(match=pattern)]
        if keys:
            r.delete(*keys)
    except Exception:
        pass
    audit_log(db=db, request=request, event_type="auth_session_revoked_all", actor_user_id=user.id, target_user_id=user.id, meta={"count": len(revoked)})
    db.commit()
    return {"ok": True}


@router.post("/sessions/revoke-others")
def revoke_other_sessions(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    r = get_redis()
    key = _user_sessions_key(str(user.id))
    hashes = [str(x) for x in (r.smembers(key) or set())]

    current_h = ""
    try:
        tok = str(request.cookies.get("core_refresh") or "").strip()
        if not tok:
            auth = str(request.headers.get("authorization") or "")
            if auth.lower().startswith("bearer "):
                tok = auth.split(" ", 1)[1].strip()
        if tok:
            current_h = _refresh_token_hash(tok)
    except Exception:
        current_h = ""

    revoked: list[str] = []
    for h in hashes:
        if current_h and h == current_h:
            continue
        r.delete(f"auth:refresh:{h}")
        revoked.append(h)
    if revoked:
        try:
            r.srem(key, *revoked)
        except Exception:
            pass
    audit_log(
        db=db,
        request=request,
        event_type="auth_session_revoked_others",
        actor_user_id=user.id,
        target_user_id=user.id,
        meta={"count": len(revoked)},
    )
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
    user.password_changed_at = datetime.utcnow()
    db.add(user)
    audit_log(db=db, request=request, event_type="auth_change_password_success", actor_user_id=user.id, target_user_id=user.id)
    db.commit()

    # Security hardening: after password change, revoke all other device sessions.
    # Keep current session alive to avoid forcing immediate re-login on the same device.
    try:
        r = get_redis()
        key = _user_sessions_key(str(user.id))
        hashes = [str(x) for x in (r.smembers(key) or set())]

        current_h = ""
        try:
            tok = str(request.cookies.get("core_refresh") or "").strip()
            if not tok:
                auth = str(request.headers.get("authorization") or "")
                if auth.lower().startswith("bearer "):
                    tok = auth.split(" ", 1)[1].strip()
            if tok:
                current_h = _refresh_token_hash(tok)
        except Exception:
            current_h = ""

        revoked: list[str] = []
        for h in hashes:
            if current_h and h == current_h:
                continue
            r.delete(f"auth:refresh:{h}")
            revoked.append(h)
        if revoked:
            try:
                r.srem(key, *revoked)
            except Exception:
                pass
            try:
                audit_log(
                    db=db,
                    request=request,
                    event_type="auth_session_revoked_others",
                    actor_user_id=user.id,
                    target_user_id=user.id,
                    meta={"count": len(revoked), "reason": "password_change"},
                )
                db.commit()
            except Exception:
                pass
    except Exception:
        pass
    return {"ok": True}
