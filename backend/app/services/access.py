"""One access policy for catalog, direct links, downloads and quiz endpoints."""
from __future__ import annotations

import uuid
from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models.module import Module, Submodule
from app.models.tag import ModuleTagMap, UserTagMap
from app.models.user import User, UserRole


def is_admin(user: User) -> bool:
    return user.role in {UserRole.admin, UserRole.superadmin}


def accessible_modules_clause(user: User):
    active = and_(Module.is_active.is_(True), Module.is_archived.is_(False))
    if is_admin(user):
        return Module.is_archived.is_(False)
    tag_match = exists(
        select(ModuleTagMap.module_id)
        .join(UserTagMap, UserTagMap.tag_id == ModuleTagMap.tag_id)
        .where(ModuleTagMap.module_id == Module.id, UserTagMap.user_id == user.id)
    )
    return and_(active, or_(Module.visibility == "public", and_(Module.visibility == "restricted", tag_match)))


def require_module_access(db: Session, user: User, module_id: uuid.UUID, *, lock: bool = False) -> Module:
    stmt = select(Module).where(Module.id == module_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    module = db.scalar(stmt)
    if module is None:
        raise HTTPException(404, "Модуль не найден")
    if is_admin(user):
        return module
    allowed = db.scalar(select(Module.id).where(Module.id == module_id, accessible_modules_clause(user)))
    if allowed is None:
        # Do not disclose the title/existence of private material by guessing a UUID.
        raise HTTPException(404, "Модуль недоступен")
    return module


def require_submodule_access(db: Session, user: User, submodule: Submodule, *, lock: bool = False) -> Module:
    module = require_module_access(db, user, submodule.module_id, lock=lock)
    if lock:
        db.refresh(submodule)
    if submodule.is_archived and not is_admin(user):
        raise HTTPException(404, "Материал в архиве")
    return module
