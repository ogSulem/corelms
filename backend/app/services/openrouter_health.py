from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.redis_client import get_redis


def openrouter_healthcheck(*, base_url: str | None = None) -> tuple[bool, str | None]:
    if not settings.openrouter_enabled:
        # Allow runtime enabling via Redis.
        try:
            r = get_redis()
            enabled_raw = (r.hget("runtime:llm", "openrouter_enabled") or b"").decode("utf-8", errors="ignore")
            if enabled_raw.strip().lower() not in {"1", "true", "yes", "on"}:
                return False, "disabled"
        except Exception:
            return False, "disabled"

    token = (settings.openrouter_api_key or "").strip()
    try:
        r = get_redis()
        rt = r.hget("runtime:llm", "openrouter_api_key")
        if rt is not None:
            token = (rt.decode("utf-8") if isinstance(rt, (bytes, bytearray)) else str(rt)).strip() or token
    except Exception:
        pass

    if not token:
        return False, "missing_token"

    base = ((str(base_url).strip() if base_url is not None else "") or str(settings.openrouter_base_url or "")).rstrip("/")
    if not base:
        return False, "missing_base_url"

    url = base + "/models"

    try:
        timeout = httpx.Timeout(connect=2.0, read=2.5, write=2.0, pool=2.0)
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {token}"})
            if r.status_code >= 400:
                return False, f"http_{r.status_code}"
        return True, None
    except Exception as e:
        return False, f"unreachable:{type(e).__name__}"
