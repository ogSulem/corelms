from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.assignment import Assignment, AssignmentStatus, AssignmentType
from app.models.module import Module, Submodule
from app.models.attempt import QuizAttempt
from app.models.quiz import Quiz
from app.models.user import User

router = APIRouter(prefix="/linear", tags=["linear"])


def can_access_submodule(db: Session, user_id: str, submodule: Submodule) -> bool:
    """
    Linear access rule: user can open submodule only if all previous submodules in the same module have a passed quiz.
    """
    # Count previous submodules in this module (by order)
    prev_count = db.scalar(
        select(func.count(Submodule.id))
        .where(Submodule.module_id == submodule.module_id, Submodule.order < submodule.order)
    )
    if prev_count is None or prev_count == 0:
        return True  # first submodule is always accessible

    # Get IDs of previous submodules
    prev_ids = list(
        db.scalars(
            select(Submodule.id)
            .where(Submodule.module_id == submodule.module_id, Submodule.order < submodule.order)
            .order_by(Submodule.order)
        ).all()
    )

    # For each previous submodule, check if user has a passed attempt for its quiz
    passed_prev = db.scalar(
        select(func.count(func.distinct(Submodule.id)))
        .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
        .join(Submodule, Submodule.quiz_id == Quiz.id)
        .where(
            QuizAttempt.user_id == user_id,
            QuizAttempt.passed == True,
            Submodule.id.in_(prev_ids),
        )
    )
    return (passed_prev or 0) == prev_count


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
def next_unlocked_submodule(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Return the first submodule the user can open but hasn't opened yet.
    Useful for dashboard/continue button.
    """
    # Find modules assigned to the user
    assigned_module_ids = [
        row.target_id
        for row in db.scalars(
            select(Assignment.target_id).where(
                Assignment.assigned_to == user.id,
                Assignment.type == AssignmentType.module,
                Assignment.status.in_([AssignmentStatus.pending, AssignmentStatus.in_progress]),
            )
        ).all()
    ]

    if not assigned_module_ids:
        return {"submodule_id": None}


@router.get("/next-unlocked-resolved")
def next_unlocked_resolved(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Same as /next-unlocked but returns resolved metadata for product-grade dashboard."""
    assigned_module_ids = [
        row.target_id
        for row in db.scalars(
            select(Assignment.target_id).where(
                Assignment.assigned_to == user.id,
                Assignment.type == AssignmentType.module,
                Assignment.status.in_([AssignmentStatus.pending, AssignmentStatus.in_progress]),
            )
        ).all()
    ]

    if not assigned_module_ids:
        return {"next": None}

    for module_id in assigned_module_ids:
        module = db.scalar(select(Module).where(Module.id == module_id))
        if module is None:
            continue

        submodules = db.scalars(
            select(Submodule)
            .where(Submodule.module_id == module_id)
            .order_by(Submodule.order)
        ).all()

        for sub in submodules:
            already_passed = db.scalar(
                select(func.count(QuizAttempt.id)).where(
                    QuizAttempt.user_id == user.id,
                    QuizAttempt.quiz_id == sub.quiz_id,
                    QuizAttempt.passed == True,
                )
            )
            if already_passed and already_passed > 0:
                continue

            if can_access_submodule(db, str(user.id), sub):
                return {
                    "next": {
                        "module_id": str(module.id),
                        "module_title": module.title,
                        "submodule_id": str(sub.id),
                        "submodule_title": sub.title,
                        "quiz_id": str(sub.quiz_id),
                        "order": int(sub.order),
                    }
                }

    return {"next": None}
