"""Atomic refresh rotation and revocation, shared by all API workers.

The stable SID is authoritative, not a browser fingerprint or a rotating hash.
WATCH/MULTI makes refresh/logout/password-change races fail closed. A brief grace
mapping plus a minimum rotation interval prevents out-of-order browser responses
from stranding other tabs. Only grace mappings temporarily contain a raw token.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from redis.exceptions import RedisError, WatchError

from app.core.client_ip import client_ip_from_request
from app.core.config import settings
from app.core.redis_client import get_redis
from app.core.tokens import password_version
from app.models.user import User

GRACE_SECONDS = 10
ROTATION_INTERVAL = 30
MAX_RETRIES = 12


def _decode(value) -> dict | None:
    try:
        result = json.loads(value) if value else None
        return result if isinstance(result, dict) else None
    except (ValueError, TypeError):
        return None


def _dump(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _token() -> str:
    return "rt_" + uuid.uuid4().hex + uuid.uuid4().hex


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def timestamp(value) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()


_limits_cache: tuple[float, tuple[int, int, int]] | None = None


def invalidate_limits() -> None:
    """Сброс кэша после сохранения настроек в админке."""
    global _limits_cache
    _limits_cache = None


def _limits() -> tuple[int, int, int]:
    """Сроки сессии: значения из интерфейса админа важнее .env.

    Читаем их не чаще раза в 30 секунд: путь входа/обновления горячий,
    а решение «сколько живёт сессия» не должно зависеть от лишнего запроса к БД.
    """
    global _limits_cache
    now = time.monotonic()
    if _limits_cache is not None and now - _limits_cache[0] < 30:
        return _limits_cache[1]
    refresh_days, idle_hours, absolute_days = (settings.session_refresh_token_days,
        settings.session_idle_timeout_hours, settings.session_absolute_timeout_days)
    try:
        from app.services.app_settings import get_platform_settings

        platform = get_platform_settings(None)
        refresh_days = platform.session_refresh_days or refresh_days
        idle_hours = platform.session_idle_hours or idle_hours
        absolute_days = platform.session_absolute_days or absolute_days
    except Exception:
        pass  # Настройки недоступны — работаем по значению окружения.
    value = (max(3600, int(refresh_days) * 86400), max(300, int(idle_hours) * 3600),
             max(3600, int(absolute_days) * 86400))
    _limits_cache = (now, value)
    return value


def _ttl(session: dict) -> int:
    return max(1, min(_limits()[0], int(timestamp(session["expires_at"]) - time.time())))


def _alive(session: dict | None) -> bool:
    if not session:
        return False
    try:
        now = time.time()
        return (now < timestamp(session["expires_at"])
                and now - timestamp(session["last_used_at"]) < int(session["idle_ttl_seconds"]))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _context(request: Request) -> dict:
    return {"ip": client_ip_from_request(request), "user_agent": str(request.headers.get("user-agent") or "")[:400]}


def _legacy(raw: dict | None, refresh_hash: str) -> dict | None:
    if not raw or raw.get("v") == 2 or not raw.get("user_id"):
        return None
    return {**raw, "sid": raw.get("sid") or str(uuid.uuid5(uuid.NAMESPACE_URL, "corelms:" + refresh_hash)),
            "refresh_hash": refresh_hash, "rotated_at": 0}


def _session_key(sid: str) -> str:
    return f"auth:session:{sid}"


def _user_key(uid: str) -> str:
    return f"auth:user_sessions:{uid}"


def unavailable() -> HTTPException:
    return HTTPException(503, "Сервис входа временно недоступен. Повторите запрос; выходить из аккаунта не нужно.")


def get_session(sid: str) -> dict | None:
    try:
        session = _decode(get_redis().get(_session_key(sid)))
        return session if _alive(session) else None
    except RedisError as exc:
        raise unavailable() from exc


def _resolve(client, token_hash: str, *, watch: bool = False) -> tuple[dict, str | None] | None:
    """Return the authoritative session and, for grace callers, the current token."""
    key, grace_key = f"auth:refresh:{token_hash}", f"auth:refresh_rot:{token_hash}"
    if watch:
        client.watch(key, grace_key)
    raw = _decode(client.get(key))
    mapping = None if raw else _decode(client.get(grace_key))
    pointer = raw or mapping
    if not pointer or not pointer.get("sid"):
        legacy = _legacy(raw, token_hash)
        if legacy and _alive(legacy):
            return legacy, None
        return None
    skey = _session_key(pointer["sid"])
    if watch:
        client.watch(skey)
    session = _decode(client.get(skey))
    if not session:
        session = _legacy(raw, token_hash)
    active_hash = mapping.get("hash") if mapping else token_hash
    if raw and session and session.get("refresh_hash") != active_hash:
        # GET(pointer) may precede another worker's atomic rotation while
        # GET(SID) follows it. Reconcile through grace, rather than return a
        # spurious 401 before WATCH has a chance to detect the conflict.
        mapping = _decode(client.get(grace_key))
        active_hash = mapping.get("hash") if mapping else None
    if not _alive(session) or session.get("refresh_hash") != active_hash:
        return None
    return session, mapping.get("token") if mapping else None


def resolve_refresh(token: str) -> dict | None:
    try:
        result = _resolve(get_redis(), _hash(token))
        return result[0] if result else None
    except RedisError as exc:
        raise unavailable() from exc


def session_matches_password(session: dict, user: User) -> bool:
    if session.get("v") == 2:
        return session.get("password_version") == password_version(user)
    # Upgrade a valid pre-v2 session without logging the user out at rollout.
    try:
        return not user.password_changed_at or timestamp(session["created_at"]) >= timestamp(user.password_changed_at)
    except (ValueError, TypeError, KeyError):
        return False


def issue_session(user: User, request: Request, *, authenticated_password_version: str | None = None) -> tuple[str, int, str]:
    now = time.time()
    token, sid = _token(), str(uuid.uuid4())
    refresh_ttl, idle_ttl, absolute_ttl = _limits()
    session = {"v": 2, "sid": sid, "user_id": str(user.id), "password_version": authenticated_password_version or password_version(user),
               "created_at": _iso(now), "last_used_at": _iso(now), "expires_at": _iso(now + absolute_ttl),
               "idle_ttl_seconds": idle_ttl, "refresh_hash": _hash(token), "rotated_at": 0, **_context(request)}
    ttl = min(refresh_ttl, absolute_ttl)
    try:
        with get_redis().pipeline() as pipe:
            pipe.setex(_session_key(sid), ttl, _dump(session))
            pipe.setex(f"auth:refresh:{session['refresh_hash']}", ttl, _dump({"v": 2, "sid": sid, "user_id": str(user.id)}))
            pipe.sadd(_user_key(str(user.id)), sid)
            pipe.expire(_user_key(str(user.id)), max(refresh_ttl, absolute_ttl))
            pipe.execute()
    except RedisError as exc:
        raise unavailable() from exc
    return token, ttl, sid


def rotate_session(token: str, user: User, request: Request) -> tuple[str, int, str] | None:
    token_hash = _hash(token)
    try:
        for _ in range(MAX_RETRIES):
            with get_redis().pipeline() as pipe:
                try:
                    found = _resolve(pipe, token_hash, watch=True)
                    if not found:
                        return None
                    session, grace_token = found
                    if session["user_id"] != str(user.id) or not session_matches_password(session, user):
                        return None
                    skey = _session_key(session["sid"])
                    pipe.watch(skey)  # Also protects a legacy-to-v2 upgrade.
                    now = time.time()
                    old_hash = session["refresh_hash"]
                    rotate = now - float(session.get("rotated_at") or 0) >= ROTATION_INTERVAL
                    next_token = _token() if rotate else (grace_token or token)
                    new_hash = _hash(next_token)
                    session.update(v=2, password_version=password_version(user), refresh_hash=new_hash,
                                   last_used_at=_iso(now), **_context(request))
                    if rotate:
                        session["rotated_at"] = now
                    ttl = _ttl(session)
                    pipe.multi()
                    pipe.setex(skey, ttl, _dump(session))
                    pipe.setex(f"auth:refresh:{new_hash}", ttl, _dump({"v": 2, "sid": session["sid"], "user_id": str(user.id)}))
                    if rotate:
                        pipe.delete(f"auth:refresh:{old_hash}")
                        pipe.setex(f"auth:refresh_rot:{old_hash}", GRACE_SECONDS,
                                   _dump({"sid": session["sid"], "hash": new_hash, "token": next_token, "user_id": str(user.id)}))
                    pipe.srem(_user_key(str(user.id)), old_hash)  # Old releases indexed rotating hashes.
                    pipe.sadd(_user_key(str(user.id)), session["sid"])
                    pipe.expire(_user_key(str(user.id)), max(_limits()[0], _limits()[2]))
                    pipe.execute()
                    return next_token, ttl, session["sid"]
                except WatchError:
                    continue
        raise unavailable()
    except RedisError as exc:
        raise unavailable() from exc


def list_sessions(user_id: str) -> list[dict]:
    try:
        redis = get_redis()
        result = []
        for member in redis.smembers(_user_key(user_id)):
            session = _decode(redis.get(_session_key(member))) or _legacy(_decode(redis.get(f"auth:refresh:{member}")), member)
            if _alive(session) and session.get("user_id") == user_id:
                result.append(session)
            # Do not prune in a non-atomic read: rotation may have just re-added a SID.
        return sorted(result, key=lambda item: item["last_used_at"], reverse=True)
    except RedisError as exc:
        raise unavailable() from exc


def revoke_sessions(user_id: str, *, only_sid: str | None = None, keep_sid: str | None = None,
                    new_password_version: str | None = None, keep_password_version: str | None = None) -> int:
    """One transaction, including concurrent login/rotation and legacy sessions.

    A password change can reauthenticate the current SID while revoking the rest.
    A concurrently logged-out session is never recreated.
    """
    user_key = _user_key(user_id)
    try:
        for _ in range(MAX_RETRIES):
            with get_redis().pipeline() as pipe:
                try:
                    pipe.watch(user_key)
                    members = pipe.smembers(user_key)
                    targets, stale, keep = [], [], None
                    for member in members:
                        skey, rkey = _session_key(member), f"auth:refresh:{member}"
                        pipe.watch(skey, rkey)
                        session = _decode(pipe.get(skey)) or _legacy(_decode(pipe.get(rkey)), member)
                        if not session or session.get("user_id") != user_id:
                            stale.append(member)
                            continue
                        # Legacy member is a hash, so also watch its stable SID.
                        pipe.watch(_session_key(session["sid"]))
                        if session["sid"] == keep_sid:
                            keep = session
                        elif (only_sid is None or session["sid"] == only_sid) and (not keep_password_version or session.get("password_version") != keep_password_version):
                            targets.append((member, session))
                    pipe.multi()
                    for member, session in targets:
                        pipe.delete(_session_key(session["sid"]), f"auth:refresh:{session['refresh_hash']}")
                        pipe.srem(user_key, member)
                    if stale:
                        pipe.srem(user_key, *stale)
                    if keep and _alive(keep) and new_password_version and keep.get("v") == 2:
                        keep.update(password_version=new_password_version, last_used_at=_iso(time.time()))
                        pipe.setex(_session_key(keep["sid"]), _ttl(keep), _dump(keep))
                    pipe.execute()
                    return len(targets)
                except WatchError:
                    continue
        raise unavailable()
    except RedisError as exc:
        raise unavailable() from exc
