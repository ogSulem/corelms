from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.asset import ContentAsset
from app.models.module import Module, Submodule
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.user import User
from app.schemas.modules_overview import ModulesOverviewResponse
from app.schemas.module import ModulePublic, SubmoduleAssetsResponse, SubmodulePublic
from app.services.modules import ModuleService
from app.services.storage import s3_prefix_has_objects

router = APIRouter(prefix="/modules", tags=["modules"])


@router.get("/overview", response_model=ModulesOverviewResponse)
def modules_overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service = ModuleService(db)
    items = service.get_modules_overview(user)
    return {"items": items}


@router.get("", response_model=list[ModulePublic])
def list_modules(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    modules = db.scalars(select(Module).where(Module.is_active == True).order_by(Module.title)).all()  # noqa: E712
    modules = [m for m in modules if s3_prefix_has_objects(prefix=f"modules/{m.id}/")]
    return [
        {
            "id": str(m.id),
            "title": m.title,
            "description": m.description,
            "difficulty": m.difficulty,
            "category": m.category,
            "is_active": m.is_active,
        }
        for m in modules
    ]


@router.get("/{module_id}", response_model=ModulePublic)
def get_module(module_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    m = db.scalar(select(Module).where(Module.id == module_id))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    if not s3_prefix_has_objects(prefix=f"modules/{m.id}/"):
        raise HTTPException(status_code=404, detail="module not found")

    return {
        "id": str(m.id),
        "title": m.title,
        "description": m.description,
        "difficulty": m.difficulty,
        "category": m.category,
        "is_active": m.is_active,
    }


@router.get("/{module_id}/submodules", response_model=list[SubmodulePublic])
def list_submodules(module_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(Submodule).where(Submodule.module_id == module_id).order_by(Submodule.order)).all()
    return [
        {
            "id": str(s.id),
            "module_id": str(s.module_id),
            "title": s.title,
            "order": s.order,
            "quiz_id": str(s.quiz_id),
            "requires_quiz": bool(getattr(s, "requires_quiz", True)),
        }
        for s in rows
    ]


@router.get("/submodules/{submodule_id}/assets", response_model=SubmoduleAssetsResponse)
def submodule_assets(submodule_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    sub = db.scalar(select(Submodule).where(Submodule.id == submodule_id))
    if sub is None:
        raise HTTPException(status_code=404, detail="submodule not found")

    stmt = (
        select(SubmoduleAssetMap.order, ContentAsset)
        .join(ContentAsset, ContentAsset.id == SubmoduleAssetMap.asset_id)
        .where(SubmoduleAssetMap.submodule_id == sub.id)
        .order_by(SubmoduleAssetMap.order)
    )
    rows = db.execute(stmt).all()

    return {
        "submodule_id": str(sub.id),
        "assets": [
            {
                "asset_id": str(asset.id),
                "object_key": asset.object_key,
                "original_filename": asset.original_filename,
                "mime_type": asset.mime_type,
                "order": int(order),
            }
            for order, asset in rows
        ],
    }


@router.get("/{module_id}/assets")
def module_assets(module_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    m = db.scalar(select(Module).where(Module.id == module_id))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    # Convention (no DB migrations): module-level materials are stored by object_key prefix.
    # IMPORTANT: lesson files are linked via SubmoduleAssetMap, so do NOT list them here.
    prefix = f"modules/{module_id}/_module/"
    assets = db.scalars(
        select(ContentAsset).where(ContentAsset.object_key.like(prefix + "%")).order_by(ContentAsset.original_filename)
    ).all()

    return {
        "module_id": str(m.id),
        "assets": [
            {
                "asset_id": str(a.id),
                "object_key": a.object_key,
                "original_filename": a.original_filename,
                "mime_type": a.mime_type,
            }
            for a in assets
        ],
    }
