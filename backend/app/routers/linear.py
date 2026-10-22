from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.module import Module, Submodule
from app.models.user import User

router = APIRouter(prefix="/linear", tags=["linear"])


def can_access_submodule(db: Session, user_id: str, submodule: Submodule) -> bool:
    import uuid
    from app.services.access import require_submodule_access
    user = db.get(User, uuid.UUID(str(user_id)))
    if user is None or submodule.is_archived:
        return False
    try:
        require_submodule_access(db, user, submodule)
        return True
    except HTTPException:
        return False


@router.get("/can-open/{submodule_id}")
def can_open_submodule(
    submodule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    import uuid
    try:
        uid = uuid.UUID(submodule_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid submodule id") from e

    submodule = db.scalar(select(Submodule).where(Submodule.id == uid))
    if not submodule:
        raise HTTPException(status_code=404, detail="submodule not found")

    allowed = can_access_submodule(db, str(user.id), submodule)
    return {"allowed": allowed}


@router.get("/next-unlocked")
def next_unlocked_submodule(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result = next_unlocked_resolved(db=db, user=user)["next"]
    return {"submodule_id": result["submodule_id"] if result else None}


@router.get("/next-unlocked-resolved")
def next_unlocked_resolved(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services.modules import ModuleService
    from app.services.learning import LearningService
    modules = ModuleService(db)._get_accessible_modules(user)
    progress = LearningService(db).get_modules_progress(user, [m.id for m in modules])
    import json
    from app.models.audit import LearningEvent, LearningEventType

    # Resume the latest visible, unfinished module, not an invented first card.
    recent_id = None
    by_id = {str(m.id): m for m in modules}
    events = db.scalars(select(LearningEvent.meta).where(LearningEvent.user_id == user.id,
        LearningEvent.type == LearningEventType.submodule_opened, LearningEvent.ref_id.is_(None))
        .order_by(LearningEvent.created_at.desc()).execution_options(yield_per=100))
    for raw in events:
        try:
            event = json.loads(raw or "{}")
            candidate = by_id.get(str(event.get("module_id"))) if isinstance(event, dict) and event.get("action") == "module_open" else None
            if candidate and not progress.get(candidate.id, {}).get("completed"):
                recent_id = candidate.id
                break
        except (TypeError, ValueError):
            continue
    modules.sort(key=lambda m: (m.id != recent_id, not bool(progress.get(m.id, {}).get("passed") or progress.get(m.id, {}).get("read_count"))))
    available = [m for m in modules if progress.get(m.id, {}).get("has_materials")]
    completed = sum(bool(progress.get(m.id, {}).get("completed")) for m in available)
    summary = {"modules_total": len(available), "modules_completed": completed}

    def step(module, p, *, updates=False):
        out = {"module_id": str(module.id), "module_title": module.title,
               "submodule_id": None, "submodule_title": None, "quiz_id": None, "order": None,
               "kind": "materials", "href": f"/modules/{module.id}", "label": "Открыть материалы",
               "passed": p.get("passed", 0), "total": p.get("total", 0), "completed": p.get("completed", False)}
        for sub in p.get("submodules", []):
            if sub["completed"]:
                continue
            take_quiz = sub["requires_quiz"] and sub["read"]
            out.update(submodule_id=sub["submodule_id"], submodule_title=sub["title"], quiz_id=sub["quiz_id"], order=sub["order"],
                       kind="quiz" if take_quiz else "lesson", label="Перейти к тесту" if take_quiz else "Открыть урок",
                       href=f"/quizzes/{sub['quiz_id']}" if take_quiz else f"/modules/{module.id}?lesson={sub['submodule_id']}")
            break
        else:
            if p.get("final_quiz_id") and not p.get("final_passed"):
                out.update(kind="final_quiz", quiz_id=p["final_quiz_id"], label="Итоговый тест", href=f"/quizzes/{p['final_quiz_id']}")
        state = "updates" if updates else "continue" if p.get("passed") or p.get("read_count") or module.id == recent_id else "start"
        return {"state": state, "next": out, **summary}

    for module in available:
        p = progress[module.id]
        if not p["completed"]:
            return step(module, p)
    for module in available:
        p = progress[module.id]
        if p.get("has_updates"):
            return step(module, p, updates=True)
    return {"state": "completed" if available else "empty", "next": None, **summary}
