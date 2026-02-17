from __future__ import annotations

import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.module import Module, Submodule
from app.models.attempt import QuizAttempt
from app.models.audit import LearningEvent, LearningEventType
from app.models.user import User

from app.services.learning import LearningService

class ModuleService:
    def __init__(self, db: Session):
        self.db = db
        self.learning_service = LearningService(db)

    def get_modules_overview(self, user: User) -> List[Dict[str, Any]]:
        """
        Возвращает обзор модулей с рассчитанным прогрессом для пользователя.
        Оптимизировано для исключения N+1 запросов.
        """
        modules = self.db.scalars(
            select(Module).where(Module.is_active == True).order_by(Module.title)
        ).all()
        
        if not modules:
            return []

        module_ids = [m.id for m in modules]
        
        # Батч-расчет прогресса через новый метод в LearningService
        progress_map = self.learning_service.get_modules_progress(user, module_ids)

        items = []
        for m in modules:
            prog = progress_map.get(m.id, {
                "total": 0,
                "passed": 0,
                "completed": False,
                "submodules": []
            })
            
            # Считаем количество прочитанных из данных батча
            read_count = sum(1 for s in prog.get("submodules", []) if s.get("read"))
            
            items.append({
                "id": str(m.id),
                "title": m.title,
                "description": m.description,
                "difficulty": m.difficulty,
                "category": m.category,
                "is_active": m.is_active,
                "progress": {
                    "read_count": read_count,
                    "total_lessons": prog.get("total", 0),
                    "passed_count": prog.get("passed", 0),
                    "final_passed": prog.get("final_passed", False),
                    "completed": prog.get("completed", False)
                }
            })
            
        return items

    def _get_reads_map(self, user_id: uuid.UUID, module_ids: List[uuid.UUID]) -> Dict[str, set[str]]:
        rows = self.db.execute(
            select(Submodule.module_id, LearningEvent.ref_id)
            .join(LearningEvent, Submodule.id == LearningEvent.ref_id)
            .where(
                LearningEvent.user_id == user_id,
                LearningEvent.type == LearningEventType.submodule_opened,
                LearningEvent.meta == "read",
                Submodule.module_id.in_(module_ids)
            )
        ).all()
        
        res = {}
        for mid, ref_id in rows:
            res.setdefault(str(mid), set()).add(str(ref_id))
        return res

    def _get_passed_quizzes(self, user_id: uuid.UUID) -> set[str]:
        rows = self.db.execute(
            select(QuizAttempt.quiz_id)
            .where(QuizAttempt.user_id == user_id, QuizAttempt.passed == True)
            .group_by(QuizAttempt.quiz_id)
        ).all()
        return {str(r[0]) for r in rows}

    def _get_submodules_data(self, module_ids: List[uuid.UUID]) -> Dict[str, List[Dict]]:
        rows = self.db.execute(
            select(Submodule.module_id, Submodule.id, Submodule.quiz_id)
            .where(Submodule.module_id.in_(module_ids))
            .order_by(Submodule.order)
        ).all()
        
        res = {}
        for mid, sid, qid in rows:
            res.setdefault(str(mid), []).append({
                "id": str(sid),
                "quiz_id": str(qid)
            })
        return res
