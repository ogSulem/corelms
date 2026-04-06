from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.rate_limit import rate_limit
from app.core.security import get_current_user
from app.models.user import User
from app.services.sales_links import get_sales_links_payload


router = APIRouter(prefix="/sales-links", tags=["sales"])


@router.get("")
def get_sales_links(
    bypass_cache: bool = Query(default=False),
    _: User = Depends(get_current_user),
    __: object = rate_limit(key_prefix="sales_links", limit=120, window_seconds=60),
):
    # bypass_cache intended for superadmin debugging
    return get_sales_links_payload(bypass_cache=bool(bypass_cache))
