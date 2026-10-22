import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from redis.exceptions import ConnectionError as RedisConnectionError
from starlette.requests import Request

from app.core.config import settings
from app.core.tokens import create_access_token, password_version
from app.models.password_reset import PasswordResetToken
from app.models.user import UserRole
from app.routers.auth import _hash_password
from app.services import auth_sessions as sessions

PASSWORD = "test-pass-123"
NEW_PASSWORD = "new-test-pass-456"


def browser_request():
    return Request({"type": "http", "headers": [(b"user-agent", b"Real browser / 1.0")], "client": ("192.0.2.5", 123)})


def login(client, user, password=PASSWORD):
    response = client.post("/auth/token", data={"username": user.name, "password": password}, headers={"User-Agent": "Same browser"})
    assert response.status_code == 200, response.text
    return response.json()


def access(tokens):
    return {"Authorization": "Bearer " + tokens["access_token"]}


def refresh(client, tokens):
    return client.post("/auth/refresh", headers={"Authorization": "Bearer " + tokens["refresh_token"]})


@pytest.fixture()
def account(db, make_user):
    user, _ = make_user()
    user.password_hash = _hash_password(PASSWORD)
    db.commit()
    return user


def test_two_logins_with_identical_user_agents_are_independent(client, account):
    first, second = login(client, account), login(client, account)
    assert first["refresh_token"] != second["refresh_token"]
    assert refresh(client, first).status_code == refresh(client, second).status_code == 200
    items = client.get("/auth/sessions", headers=access(first)).json()["items"]
    current = [item for item in items if item["current"]]
    assert len(current) == 1 and current[0]["user_agent"] == "testclient"  # Refresh records actual caller UA.
    assert len({item["session_id"] for item in items}) == len(items)


def test_parallel_rotation_has_one_successor_and_no_refresh_chains(account):
    request = browser_request()
    original, _, sid = sessions.issue_session(account, request)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: sessions.rotate_session(original, account, request), range(8)))
    assert all(results)
    assert len({result[0] for result in results}) == 1
    successor = results[0][0]
    assert successor != original
    # A fast refresh on the new token must not create B->C while A->B is in flight.
    assert sessions.rotate_session(successor, account, request)[0] == successor
    assert sessions.rotate_session(original, account, request)[0] == successor
    assert sessions.get_session(sid)["refresh_hash"] == hashlib.sha256(successor.encode()).hexdigest()


def test_logout_with_an_old_grace_token_revokes_rotated_access_and_refresh(client, account):
    old = login(client, account)
    rotated = refresh(client, old).json()
    assert client.post("/auth/logout", headers={"Authorization": "Bearer " + old["refresh_token"]}).status_code == 200
    for token in (old, rotated):
        assert refresh(client, token).status_code == 401
        assert client.get("/auth/me", headers=access(token)).status_code == 401


def test_session_revocation_is_sid_bound_not_refresh_hash_bound(client, account):
    current, other = login(client, account), login(client, account)
    current = refresh(client, current).json()
    assert client.post("/auth/sessions/revoke-others", headers=access(current)).status_code == 200
    assert refresh(client, current).status_code == 200
    assert refresh(client, other).status_code == 401
    assert client.get("/auth/me", headers=access(other)).status_code == 401
    assert client.post("/auth/sessions/revoke-all", headers=access(current)).status_code == 200
    assert client.get("/auth/me", headers=access(current)).status_code == 401


def test_password_change_preserves_current_session_and_revokes_every_old_jwt(client, account):
    current, other = login(client, account), login(client, account)
    response = client.post("/auth/change-password", headers=access(current), json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert response.status_code == 200, response.text
    for old in (current, other):
        assert client.get("/auth/me", headers=access(old)).status_code == 401
    renewed = refresh(client, current)
    assert renewed.status_code == 200, renewed.text
    assert client.get("/auth/me", headers=access(renewed.json())).status_code == 200
    assert refresh(client, other).status_code == 401
    assert login(client, account, NEW_PASSWORD)["access_token"]


def test_wrong_current_password_does_not_log_the_user_out(client, account):
    current = login(client, account)
    wrong = client.post("/auth/change-password", headers=access(current), json={"current_password": "wrong", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 400
    assert client.get("/auth/me", headers=access(current)).status_code == 200


def test_temporary_password_is_enforced_on_backend_not_only_ui(client, account, db):
    account.must_change_password = True
    db.commit()
    tokens = login(client, account)
    assert client.get("/auth/me", headers=access(tokens)).json()["must_change_password"]
    for path in ("/modules", "/me/history", "/linear/next-unlocked-resolved"):
        response = client.get(path, headers=access(tokens))
        assert response.status_code == 403, (path, response.text)
        assert "password_change_required" in response.text
    response = client.post("/auth/change-password", headers=access(tokens), json={
        "current_password": PASSWORD, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD, "phone": "+48555123456"})
    assert response.status_code == 200, response.text
    renewed = refresh(client, tokens)
    assert renewed.status_code == 200
    assert client.get("/modules", headers=access(renewed.json())).status_code == 200


def test_admin_cannot_call_superadmin_only_sales_mutations(client, admin_headers):
    response = client.post("/sales-files/presign-upload", headers=admin_headers,
                           json={"section": "photos", "filename": "picture.png", "content_type": "image/png"})
    assert response.status_code == 403, response.text


def test_public_register_cannot_promote_role(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_public_register", True)
    response = client.post("/auth/register", json={"name": "No promotion", "password": PASSWORD, "role": "superadmin"})
    assert response.status_code == 200
    assert client.get("/auth/me", headers=access(response.json())).json()["role"] == "user"


def test_admin_password_reset_revokes_access_in_the_same_second(client, db, account, admin_headers):
    tokens = login(client, account)
    response = client.post(f"/admin/users/{account.id}/reset-password", headers=admin_headers,
                           json={"password": NEW_PASSWORD, "must_change_password": False})
    assert response.status_code == 200, response.text
    assert client.get("/auth/me", headers=access(tokens)).status_code == 401
    assert refresh(client, tokens).status_code == 401
    assert client.get("/auth/me", headers=access(login(client, account, NEW_PASSWORD))).status_code == 200


def test_reset_link_is_single_use_and_revokes_other_reset_links_and_sessions(client, db, account):
    tokens = login(client, account)
    raw1, raw2 = uuid.uuid4().hex, uuid.uuid4().hex
    for raw in (raw1, raw2):
        db.add(PasswordResetToken(user_id=account.id, token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                                  expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
    db.commit()
    response = client.post("/auth/reset-password/confirm", json={"token": raw1, "new_password": NEW_PASSWORD})
    assert response.status_code == 200, response.text
    for raw in (raw1, raw2):
        assert client.post("/auth/reset-password/confirm", json={"token": raw, "new_password": PASSWORD}).status_code == 400
    assert client.get("/auth/me", headers=access(tokens)).status_code == 401
    assert refresh(client, tokens).status_code == 401


def test_legacy_refresh_upgrades_without_device_or_progress_loss(client, account, redis_memory):
    token, sid = "rt_legacy_test", str(uuid.uuid4())
    h = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.utcnow()
    redis_memory.setex(f"auth:refresh:{h}", 3600, json.dumps({"sid": sid, "user_id": str(account.id),
        "created_at": now.isoformat(), "last_used_at": now.isoformat(), "expires_at": (now + timedelta(days=30)).isoformat(),
        "idle_ttl_seconds": 43200, "user_agent": "Legacy browser"}))
    redis_memory.sadd(f"auth:user_sessions:{account.id}", h)
    legacy_access = jwt.encode({"sub": str(account.id), "iss": settings.jwt_issuer, "exp": time.time() + 100}, settings.jwt_secret_key)
    assert client.get("/auth/me", headers={"Authorization": "Bearer " + legacy_access}).status_code == 401
    result = refresh(client, {"refresh_token": token})
    assert result.status_code == 200, result.text
    assert sessions.get_session(sid)["password_version"] == password_version(account)
    assert client.get("/auth/me", headers=access(result.json())).status_code == 200


def test_grace_mapping_does_not_bypass_absolute_or_idle_expiration(account, redis_memory):
    token, _, sid = sessions.issue_session(account, browser_request())
    sessions.rotate_session(token, account, browser_request())
    session = sessions.get_session(sid)
    session["last_used_at"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    redis_memory.setex(f"auth:session:{sid}", 3600, json.dumps(session))
    assert sessions.rotate_session(token, account, browser_request()) is None
    assert sessions.get_session(sid) is None


def test_redis_outage_is_temporary_failure_not_invalid_credentials(client, account, monkeypatch):
    tokens = login(client, account)
    class Unavailable:
        def get(self, *args):
            raise RedisConnectionError("offline")
    monkeypatch.setattr(sessions, "get_redis", lambda: Unavailable())
    assert client.get("/auth/me", headers=access(tokens)).status_code == 503
    assert refresh(client, tokens).status_code == 503


def test_refresh_and_revoke_race_never_resurrects_a_session(account):
    for _ in range(8):
        token, _, sid = sessions.issue_session(account, browser_request())
        with ThreadPoolExecutor(max_workers=2) as pool:
            rotating = pool.submit(sessions.rotate_session, token, account, browser_request())
            revoking = pool.submit(sessions.revoke_sessions, str(account.id), only_sid=sid)
            result = rotating.result()
            revoking.result()
        assert sessions.get_session(sid) is None
        assert sessions.resolve_refresh(token) is None
        if result:
            assert sessions.resolve_refresh(result[0]) is None


@pytest.mark.skipif(not os.getenv("TEST_AUTH_REDIS_URL"), reason="disposable real Redis URL not supplied")
def test_real_redis_atomic_rotation_and_logout(account, monkeypatch):
    import redis
    client = redis.Redis.from_url(os.environ["TEST_AUTH_REDIS_URL"], decode_responses=True)
    # No FLUSHDB: even the integration test owns only this randomly named user.
    monkeypatch.setattr(sessions, "get_redis", lambda: client)
    test_parallel_rotation_has_one_successor_and_no_refresh_chains(account)
    test_refresh_and_revoke_race_never_resurrects_a_session(account)
    sessions.revoke_sessions(str(account.id))
    client.delete(f"auth:user_sessions:{account.id}")


def test_logout_revokes_sid_even_after_refresh_grace_expires(client, account, redis_memory):
    old = login(client, account)
    rotated = refresh(client, old).json()
    redis_memory.delete("auth:refresh_rot:" + hashlib.sha256(old["refresh_token"].encode()).hexdigest())
    result = client.post("/auth/logout", headers={"Authorization": "Bearer " + old["refresh_token"], "Cookie": "core_token=" + old["access_token"]})
    assert result.status_code == 200
    assert client.get("/auth/me", headers=access(rotated)).status_code == 401
    assert refresh(client, rotated).status_code == 401


def test_login_cannot_authenticate_old_password_if_reset_races_session_creation(client, account, monkeypatch):
    from app.db.session import SessionLocal
    from app.models.user import User
    original = sessions.issue_session
    replacement_hash = _hash_password(NEW_PASSWORD)
    def raced(user, request, **kwargs):
        with SessionLocal() as other:
            other.get(User, user.id).password_hash = replacement_hash
            other.commit()
        return original(user, request, **kwargs)
    monkeypatch.setattr(sessions, "issue_session", raced)
    tokens = login(client, account)
    assert client.get("/auth/me", headers=access(tokens)).status_code == 401
    assert refresh(client, tokens).status_code == 401


def test_password_change_never_adopts_a_concurrent_admin_reset_password(client, account, monkeypatch):
    from app.db.session import SessionLocal
    from app.models.user import User
    tokens = login(client, account)
    original = sessions.revoke_sessions
    replacement_hash = _hash_password("administrator-reset-789")
    def raced(user_id, **kwargs):
        with SessionLocal() as other:
            other.get(User, uuid.UUID(user_id)).password_hash = replacement_hash
            other.commit()
        return original(user_id, **kwargs)
    monkeypatch.setattr(sessions, "revoke_sessions", raced)
    result = client.post("/auth/change-password", headers=access(tokens), json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert result.status_code == 200
    assert refresh(client, tokens).status_code == 401


def test_parallel_password_changes_serialize_on_postgresql(client, account):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.db.session import engine
    if engine.dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL row locks")
    tokens = [login(client, account), login(client, account)]
    barrier = Barrier(2)
    def change(index):
        barrier.wait(timeout=10)
        return client.post("/auth/change-password", headers=access(tokens[index]), json={"current_password": PASSWORD, "new_password": NEW_PASSWORD + str(index)})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, (0, 1)))
    assert sum(result.status_code == 200 for result in results) == 1
    winner = next(index for index, result in enumerate(results) if result.status_code == 200)
    assert results[1 - winner].status_code in (400, 401)
    assert refresh(client, tokens[winner]).status_code == 200
    assert refresh(client, tokens[1 - winner]).status_code == 401


def test_admin_reset_wins_over_in_flight_password_change(client, account, admin_headers, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.db.session import engine
    if engine.dialect.name != "postgresql":
        pytest.skip("requires concurrent PostgreSQL transactions")
    tokens = login(client, account)
    committed, reset_finished = Event(), Event()
    revoke = sessions.revoke_sessions
    def delayed(user_id, **kwargs):
        if kwargs.get("keep_sid"):
            committed.set()
            assert reset_finished.wait(10)
        return revoke(user_id, **kwargs)
    monkeypatch.setattr(sessions, "revoke_sessions", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        changing = pool.submit(client.post, "/auth/change-password", headers=access(tokens), json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
        assert committed.wait(10)
        try:
            reset = client.post(f"/admin/users/{account.id}/reset-password", headers=admin_headers, json={"password": "admin-latest-password", "must_change_password": False})
            assert reset.status_code == 200
        finally:
            reset_finished.set()
        assert changing.result(timeout=10).status_code == 200
    assert refresh(client, tokens).status_code == 401
    assert client.get("/auth/me", headers=access(tokens)).status_code == 401
    fresh = login(client, account, password="admin-latest-password")
    assert client.get("/auth/me", headers=access(fresh)).status_code == 200
