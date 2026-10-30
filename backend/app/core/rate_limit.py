from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.core.config import settings
from app.core.client_ip import client_ip_from_request
from app.core.redis_client import get_redis


@dataclass(frozen=True)
class RateLimit:
    key: str
    limit: int
    window_seconds: int


def _client_ip(request: Request) -> str:
    ip = client_ip_from_request(request)
    if ip:
        return ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "error_code": "rate_limited",
            "error_message": "Слишком много запросов. Подождите немного и повторите.",
            "error_hint": f"Повторите через {int(retry_after)} сек.",
        },
        headers={"Retry-After": str(int(retry_after))},
    )


def hit(*, key: str, limit: int, window_seconds: int) -> None:
    """Учесть одну попытку. Бросает 429, если лимит по ключу исчерпан.

    Ключ задаёт вызывающая сторона: он может быть адресом клиента (защита от
    потока с одного хоста) или конкретной учётной записью (защита от подбора).
    """
    r = get_redis()
    try:
        current = r.incr(key)
        if current == 1:
            r.expire(key, int(window_seconds))
    except Exception:
        return
    if int(current) > int(limit):
        try:
            ttl = r.ttl(key)
        except Exception:
            ttl = None
        raise _too_many(int(ttl) if ttl and ttl > 0 else int(window_seconds))


def rate_limit(*, key_prefix: str, limit: int, window_seconds: int):
    async def _dep(request: Request) -> RateLimit:
        ip = _client_ip(request)
        key = f"rl:{key_prefix}:{request.method}:{request.url.path}:{ip}"
        hit(key=key, limit=limit, window_seconds=window_seconds)
        return RateLimit(key=key, limit=int(limit), window_seconds=int(window_seconds))

    return Depends(_dep)
