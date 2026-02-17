from __future__ import annotations

import json

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.security_audit import SecurityAuditEvent


def _request_id(request: Request) -> str | None:
    rid = getattr(getattr(request, "state", None), "request_id", None)
    rid = str(rid or "").strip()
    return rid or None


def _client_ip(request: Request) -> str | None:
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
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
