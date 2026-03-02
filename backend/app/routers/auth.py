import uuid
import hashlib
import json
import ipaddress
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
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
    position: str | None = None
    role: UserRole = UserRole.employee
    password: str


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
    payload = {
        "user_id": str(user.id),
        "created_at": now.isoformat(),
        "last_used_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=abs_ttl)).isoformat(),
        "idle_ttl_seconds": int(idle_ttl),
        "ip": ip,
        "ip_fp": ip_fp,
        "user_agent": ua,
    }
    r = get_redis()
    r.setex(f"auth:refresh:{h}", int(refresh_ttl), json.dumps(payload, ensure_ascii=False))
    r.sadd(_user_sessions_key(str(user.id)), h)
    r.expire(_user_sessions_key(str(user.id)), int(refresh_ttl))
    return token, refresh_ttl


def _rotate_refresh_session(*, refresh_token: str, request: Request) -> tuple[str, str, int, dict, str, str] | None:
    tok = str(refresh_token or "").strip()
    if not tok:
        return None
    h = _refresh_token_hash(tok)
    r = get_redis()
    raw = r.get(f"auth:refresh:{h}")
    if not raw:
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
    r.setex(f"auth:refresh:{new_h}", int(refresh_ttl), json.dumps(sess, ensure_ascii=False))
    r.delete(f"auth:refresh:{h}")

    uid = str(sess.get("user_id") or "").strip()
    if uid:
        key = _user_sessions_key(uid)
        r.srem(key, h)
        r.sadd(key, new_h)
        r.expire(key, int(refresh_ttl))

    return new_token, uid, refresh_ttl, sess, h, new_h


def _public_role(role: UserRole) -> str:
    if role == UserRole.admin:
        return "admin"
    return "user"


def _client_ip_from_request(request: Request) -> str | None:
    if bool(getattr(settings, "trust_proxy_headers", False)):
        xri = str(request.headers.get("x-real-ip") or "").strip()
        if xri:
            return xri
        xff = str(request.headers.get("x-forwarded-for") or "")
        if xff:
            ip = xff.split(",")[0].strip()
            if ip:
                return ip
    if request.client and request.client.host:
        return request.client.host
    return None


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
        user = db.scalar(select(User).where(User.name == login_raw))
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
    try:
        auth = str(request.headers.get("authorization") or "")
        tok = ""
        if auth.lower().startswith("bearer "):
            tok = auth.split(" ", 1)[1].strip()
        if tok:
            current_h = _refresh_token_hash(tok)
    except Exception:
        current_h = ""

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
        items.append(
            SessionItem(
                session_id=_session_id_from_hash(h),
                created_at=str(sess.get("created_at") or "") or None,
                last_used_at=str(sess.get("last_used_at") or "") or None,
                expires_at=str(sess.get("expires_at") or "") or None,
                ip=str(sess.get("ip") or "") or None,
                ip_fp=str(sess.get("ip_fp") or "") or None,
                user_agent=str(sess.get("user_agent") or "") or None,
                current=bool(current_h and h == current_h),
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
        if _session_id_from_hash(h) == sid:
            target = h
            break
    if not target:
        return {"ok": True}
    r.delete(f"auth:refresh:{target}")
    r.srem(key, target)
    audit_log(db=db, request=request, event_type="auth_session_revoked", actor_user_id=user.id, target_user_id=user.id, meta={"session_id": sid})
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
        auth = str(request.headers.get("authorization") or "")
        tok = ""
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
    user.must_change_password = False
    user.password_changed_at = datetime.utcnow()
    db.add(user)
    audit_log(db=db, request=request, event_type="auth_change_password_success", actor_user_id=user.id, target_user_id=user.id)
    db.commit()
    return {"ok": True}
