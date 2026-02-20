from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.core.config import settings
from app.core.redis_client import get_redis


@dataclass(frozen=True)
class RateLimit:
    key: str
    limit: int
    window_seconds: int


def _client_ip(request: Request) -> str:
    if bool(getattr(settings, "trust_proxy_headers", False)):
        xri = str(request.headers.get("x-real-ip") or "").strip()
        if xri:
            return xri
        xff = request.headers.get("x-forwarded-for")
        if xff:
            ip = xff.split(",")[0].strip()
            if ip:
                return ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit(*, key_prefix: str, limit: int, window_seconds: int):
    async def _dep(request: Request) -> RateLimit:
        r = get_redis()
        ip = _client_ip(request)
        key = f"rl:{key_prefix}:{request.method}:{request.url.path}:{ip}"

        try:
            current = r.incr(key)
            if current == 1:
                r.expire(key, int(window_seconds))
        except Exception:
            return RateLimit(key=key, limit=int(limit), window_seconds=int(window_seconds))

        if int(current) > int(limit):
            ttl = r.ttl(key)
            retry_after = int(ttl) if ttl and ttl > 0 else int(window_seconds)
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        return RateLimit(key=key, limit=int(limit), window_seconds=int(window_seconds))

    return Depends(_dep)
