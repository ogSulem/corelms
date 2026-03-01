from __future__ import annotations

import json

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.security_audit import SecurityAuditEvent


def _request_id(request: Request) -> str | None:
    rid = getattr(getattr(request, "state", None), "request_id", None)
    rid = str(rid or "").strip()
    return rid or None


def _client_ip(request: Request) -> str | None:
    if bool(getattr(settings, "trust_proxy_headers", False)):
        fwd = str(request.headers.get("forwarded") or "").strip()
        if fwd:
            # Forwarded: for=1.2.3.4;proto=https;host=...
            try:
                parts = [p.strip() for p in fwd.split(";") if p.strip()]
                for part in parts:
                    if part.lower().startswith("for="):
                        v = part.split("=", 1)[1].strip().strip('"').strip()
                        if v.startswith("[") and "]" in v:
                            v = v[1 : v.index("]")]
                        if ":" in v and not v.count(":") > 1:
                            v = v.split(":", 1)[0]
                        if v:
                            return v
            except Exception:
                pass

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


def audit_log(
    *,
    db: Session,
    request: Request,
    event_type: str,
    actor_user_id=None,
    target_user_id=None,
    meta: dict | str | None = None,
) -> None:
    if isinstance(meta, dict):
        meta_str = json.dumps(meta, ensure_ascii=False)
    elif isinstance(meta, str):
        meta_str = meta
    else:
        meta_str = None

    db.add(
        SecurityAuditEvent(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            event_type=str(event_type),
            meta=meta_str,
            request_id=_request_id(request),
            ip=_client_ip(request),
        )
    )
