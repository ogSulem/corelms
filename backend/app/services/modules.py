from __future__ import annotations

import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func
from sqlalchemy.orm import Session
import json

from app.core.redis_client import get_redis
from app.models.module import Module, Submodule
from app.models.attempt import QuizAttempt
from app.models.audit import LearningEvent, LearningEventType
from app.models.user import User

from app.services.learning import LearningService


def modules_get_rev() -> int:
    try:
        r = get_redis()
        raw = r.get("modules:rev")
        if raw is None:
            return 0
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        return int(str(raw or "0").strip() or "0")
    except Exception:
        return 0


def modules_bump_rev(*, reason: str | None = None) -> int:
    try:
        r = get_redis()
        v = int(r.incr("modules:rev"))
        try:
            r.expire("modules:rev", 60 * 60 * 24 * 30)
        except Exception:
            pass
        try:
            r.publish("modules:changed", str(reason or ""))
        except Exception:
            pass
        return v
    except Exception:
        return modules_get_rev()


def modules_invalidate_storage_cache(*, module_storage_prefix: str | None = None) -> None:
    # Invalidate the cached listing of module prefixes.
    try:
        s3_invalidate_common_prefixes(prefix="modules/", delimiter="/")
    except Exception:
        pass

    # Invalidate the specific module prefix check if known.
    try:
        pfx = str(module_storage_prefix or "").strip()
        if pfx and (not pfx.endswith("/")):
            pfx = pfx + "/"
        if pfx:
            s3_invalidate_prefix_has_objects(prefix=pfx)
    except Exception:
        pass

class ModuleService:
    def __init__(self, db: Session):
        self.db = db
        self.learning_service = LearningService(db)

    def get_modules_overview(self, user: User) -> List[Dict[str, Any]]:
        """
        Возвращает обзор модулей с рассчитанным прогрессом для пользователя.
        Оптимизировано для исключения N+1 запросов.
        """
        modules = self.db.scalars(select(Module).where(Module.is_active == True).order_by(Module.title)).all()  # noqa: E712
        
        if not modules:
            return []

        module_ids = [m.id for m in modules]
        
        # Fast path: compact progress for list views (cached briefly).
        progress_map = self.learning_service.get_modules_progress_compact(user, module_ids)

        items = []
        for m in modules:
            prog = progress_map.get(
                m.id,
                {
                    "total_lessons": 0,
                    "passed_count": 0,
                    "read_count": 0,
                    "final_passed": False,
                    "completed": False,
                },
            )
            
            items.append({
                "id": str(m.id),
                "title": m.title,
                "description": m.description,
                "difficulty": m.difficulty,
                "category": m.category,
                "is_active": m.is_active,
                "progress": {
                    "read_count": int(prog.get("read_count", 0) or 0),
                    "total_lessons": int(prog.get("total_lessons", 0) or 0),
                    "passed_count": int(prog.get("passed_count", 0) or 0),
                    "final_passed": bool(prog.get("final_passed", False)),
                    "completed": bool(prog.get("completed", False)),
                }
            })
            
        return items

    def _get_reads_map(self, user_id: uuid.UUID, module_ids: List[uuid.UUID]) -> Dict[str, set[str]]:
        def _meta_action_is_read(meta: str | None) -> bool:
            if not meta:
                return False
            if str(meta).strip().lower() == "read":
                return True
            try:
                obj = json.loads(str(meta))
                if isinstance(obj, dict) and str(obj.get("action") or "").strip().lower() == "read":
                    return True
            except Exception:
                return False
            return False

        rows = self.db.execute(
            select(Submodule.module_id, LearningEvent.ref_id, LearningEvent.meta)
            .join(LearningEvent, Submodule.id == LearningEvent.ref_id)
            .where(
                LearningEvent.user_id == user_id,
                LearningEvent.type == LearningEventType.submodule_opened,
                LearningEvent.meta.is_not(None),
                Submodule.module_id.in_(module_ids)
            )
        ).all()
        
        res = {}
        for mid, ref_id, meta in rows:
            if not _meta_action_is_read(meta):
                continue
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
