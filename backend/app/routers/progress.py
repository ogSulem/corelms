from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.progress import ModuleProgressResponse
from app.services.learning import LearningService

router = APIRouter(prefix="/progress", tags=["progress"])


@router.get("/modules/{module_id}", response_model=ModuleProgressResponse)
def module_progress(module_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        mid = uuid.UUID(module_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid module_id") from e
        
    service = LearningService(db)
    progress = service.get_module_progress(user, mid)
    
    if progress is None:
        raise HTTPException(status_code=404, detail="module not found")
        
    return progress
