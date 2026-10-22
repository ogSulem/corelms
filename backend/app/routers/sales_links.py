from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.rate_limit import rate_limit
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.services.sales_links import get_sales_links_payload, source_url


router = APIRouter(prefix="/sales-links", tags=["sales"])


@router.get("")
def get_sales_links(
    bypass_cache: bool = Query(default=False),
    user: User = Depends(get_current_user),
    __: object = rate_limit(key_prefix="sales_links", limit=30, window_seconds=60),
):
    if bypass_cache and user.role != UserRole.superadmin:
        raise HTTPException(403, "Принудительное обновление доступно только суперадминистратору")
    return {**get_sales_links_payload(bypass_cache=bool(bypass_cache)),
            "source_url": source_url() if user.role == UserRole.superadmin else None}
