from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.core.security import get_current_user, require_roles
from app.core.security_audit_log import audit_log
from app.db.session import get_db
from app.models.asset import ContentAsset
from app.models.audit import LearningEvent, LearningEventType
from app.models.module import Module, Submodule
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.user import User, UserRole
from app.schemas.asset import AssetCreateRequest, AssetCreateResponse, AssetGetUrlResponse
from app.services.skills import record_activity_and_award_xp
from app.services.storage import presign_get, presign_put

router = APIRouter(prefix="/assets", tags=["assets"])


@router.post("/presign-upload", response_model=AssetCreateResponse)
def presign_upload(
    request: Request,
    body: AssetCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="asset_presign_upload", limit=30, window_seconds=60),
):
    existing = db.scalar(select(ContentAsset).where(ContentAsset.object_key == body.object_key))
    if existing is not None:
        raise HTTPException(status_code=409, detail="object_key already exists")

    asset = ContentAsset(
        bucket=settings.s3_bucket,
        object_key=body.object_key,
        original_filename=body.original_filename,
        mime_type=body.mime_type,
        created_by=user.id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    url = presign_put(object_key=asset.object_key, content_type=asset.mime_type)
    audit_log(
        db=db,
        request=request,
        event_type="admin_presign_asset_upload",
        actor_user_id=user.id,
        meta={"asset_id": str(asset.id), "object_key": asset.object_key, "mime_type": asset.mime_type},
    )
    db.commit()
    return AssetCreateResponse(asset_id=str(asset.id), upload_url=url)


@router.get("/{asset_id}/presign-download", response_model=AssetGetUrlResponse)
def presign_download(
    request: Request,
    asset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: object = rate_limit(key_prefix="asset_presign_download", limit=120, window_seconds=60),
):
    try:
        aid = uuid.UUID(asset_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid asset id") from e

    asset = db.scalar(select(ContentAsset).where(ContentAsset.id == aid))
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")

    # Hardening: avoid leaking arbitrary assets by UUID.
    # - Non-admin users must only access assets that are part of active learning content.
    # - Admin upload ZIP artifacts must never be downloadable by non-admins.
    object_key = str(asset.object_key or "")
    if user.role != UserRole.admin and object_key.startswith("uploads/admin/"):
        raise HTTPException(status_code=403, detail="forbidden")

    if user.role != UserRole.admin:
        linked_to_active = (
            db.scalar(
                select(func.count(ContentAsset.id))
                .select_from(ContentAsset)
                .join(SubmoduleAssetMap, SubmoduleAssetMap.asset_id == ContentAsset.id)
                .join(Submodule, Submodule.id == SubmoduleAssetMap.submodule_id)
                .join(Module, Module.id == Submodule.module_id)
                .where(ContentAsset.id == aid, Module.is_active == True)  # noqa: E712
            )
            or 0
        )

        module_prefix_active = 0
        if object_key.startswith("modules/"):
            parts = object_key.split("/")
            mid = parts[1] if len(parts) >= 2 else ""
            if mid:
                module_prefix_active = (
                    db.scalar(select(func.count(Module.id)).select_from(Module).where(Module.id == mid, Module.is_active == True))  # noqa: E712
                    or 0
                )

        if int(linked_to_active) <= 0 and int(module_prefix_active) <= 0:
            raise HTTPException(status_code=403, detail="forbidden")

    # Count asset views as activity for streak, but do not award XP.
    # Important: update streak BEFORE inserting the learning event to avoid autoflush affecting streak init.
    record_activity_and_award_xp(db, user_id=str(user.id), xp=0)

    db.add(LearningEvent(user_id=user.id, type=LearningEventType.asset_viewed, ref_id=asset.id))
    db.commit()

    audit_log(
        db=db,
        request=request,
        event_type="asset_presign_download",
        actor_user_id=user.id,
        meta={"asset_id": str(asset.id), "object_key": str(asset.object_key), "mime_type": str(asset.mime_type or "")},
    )
    db.commit()

    url = presign_get(object_key=asset.object_key)
    return AssetGetUrlResponse(asset_id=str(asset.id), download_url=url)
