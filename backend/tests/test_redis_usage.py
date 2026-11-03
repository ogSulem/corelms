"""Redis: соединения, лимиты и сроки жизни ключей.

Redis здесь не «просто кэш»: в нём живут сессии с отзывом, счётчики лимитов,
сессии тестов, очереди RQ и блокировки импорта. Поэтому проверяем не только
«работает», но и «не течёт»: одно соединение на процесс, у каждого ключа есть
срок жизни, а лимит не может стать вечным из-за сбоя между INCR и EXPIRE.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException


def test_queue_and_job_share_one_redis_client(monkeypatch):
    """Опрос списка задач не должен создавать новый пул соединений на каждую задачу."""
    import redis

    from app.core import queue as queue_module
    from app.core import redis_client

    created: list[dict] = []

    class StubRedis:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def from_url(url, **kwargs):
        created.append(kwargs)
        return StubRedis(**kwargs)

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(from_url))
    redis_client.get_redis_rq.cache_clear()
    try:
        first = queue_module.get_queue("corelms_import")
        second = queue_module.get_queue("corelms_media")
        assert first.connection is second.connection, "у очередей должен быть один клиент"
        assert len(created) == 1
        assert created[0].get("decode_responses") is not True, "RQ хранит байты, декодирование их ломает"
        # Ошибка выборки задачи (нет соединения) не должна пересоздавать клиент.
        assert queue_module.fetch_job("missing") is None
        assert len(created) == 1
    finally:
        redis_client.get_redis_rq.cache_clear()


def test_rate_limit_key_always_has_ttl(redis_memory):
    from app.core import rate_limit

    redis_memory.delete("rl:test:key")
    rate_limit.hit(key="rl:test:key", limit=5, window_seconds=60)
    assert 0 < redis_memory.ttl("rl:test:key") <= 60


def test_rate_limit_heals_a_key_left_without_ttl(redis_memory):
    """Ключ без TTL раньше блокировал клиента навсегда: счётчик не сбрасывался."""
    from app.core import rate_limit

    redis_memory.set("rl:stuck:key", 100)
    assert redis_memory.ttl("rl:stuck:key") == -1
    rate_limit.hit(key="rl:stuck:key", limit=1000, window_seconds=60)
    assert redis_memory.ttl("rl:stuck:key") > 0


def test_rate_limit_still_returns_429_with_retry_after(redis_memory):
    from app.core import rate_limit

    redis_memory.set("rl:over:key", 3)
    redis_memory.expire("rl:over:key", 30)
    with pytest.raises(HTTPException) as error:
        rate_limit.hit(key="rl:over:key", limit=3, window_seconds=30)
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "30"


def test_rate_limit_fails_open_when_redis_is_unavailable(monkeypatch):
    """Без Redis запросы не должны падать: доступность важнее лимита."""
    from app.core import rate_limit

    def broken():
        raise RuntimeError("redis is down")

    monkeypatch.setattr(rate_limit, "get_redis", broken)
    rate_limit.hit(key="rl:any", limit=1, window_seconds=60)  # не бросает


def test_session_keys_are_not_stored_forever(redis_memory, client, make_user):
    """Сессия и её обратные индексы живут по TTL, иначе Redis растёт молча."""
    _user, headers = make_user()
    assert client.get("/me/profile", headers=headers).status_code == 200
    keys = [key for key in redis_memory.scan_iter(match="auth:*") if not key.startswith("auth:refresh_rot:")]
    assert keys, "сессия должна храниться в Redis"
    for key in keys:
        assert redis_memory.ttl(key) > 0, f"ключ без срока жизни: {key}"
