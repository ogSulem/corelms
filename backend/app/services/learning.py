from __future__ import annotations

import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session
import json

from app.models.module import Module, ModuleSkillMap, Submodule
from app.models.attempt import QuizAttempt
from app.models.audit import LearningEvent, LearningEventType
from app.models.user import User

class LearningService:
    def __init__(self, db: Session):
        self.db = db

    def get_modules_progress(self, user: User, module_ids: List[uuid.UUID]) -> Dict[uuid.UUID, Dict[str, Any]]:
        """
        Batch source of truth for progress calculation.
        """
        if not module_ids:
            return {}

        modules = self.db.scalars(
            select(Module).where(Module.id.in_(module_ids))
        ).all()
        
        all_submodules = self.db.scalars(
            select(Submodule).where(Submodule.module_id.in_(module_ids)).order_by(Submodule.module_id, Submodule.order)
        ).all()
        
        submodules_by_module = {}
        all_quiz_ids = []
        all_sub_ids = []
        for s in all_submodules:
            submodules_by_module.setdefault(s.module_id, []).append(s)
            if bool(getattr(s, "requires_quiz", True)):
                all_quiz_ids.append(s.quiz_id)
            all_sub_ids.append(s.id)
        
        for m in modules:
            if m.final_quiz_id:
                all_quiz_ids.append(m.final_quiz_id)

        # Batch load best attempts
        best_attempts = {}
        if all_quiz_ids:
            rows = self.db.execute(
                select(QuizAttempt.quiz_id, func.max(QuizAttempt.score))
                .where(
                    QuizAttempt.user_id == user.id, 
                    QuizAttempt.quiz_id.in_(all_quiz_ids), 
                    QuizAttempt.passed == True
                )
                .group_by(QuizAttempt.quiz_id)
            ).all()
            best_attempts = {r[0]: r[1] for r in rows}

        # Batch load read confirmations
        read_ids = set()
        if all_sub_ids:
            read_ids = set(
                self.db.scalars(
                    select(LearningEvent.ref_id).where(
                        LearningEvent.user_id == user.id,
                        LearningEvent.type == LearningEventType.submodule_opened,
                        LearningEvent.meta == "read",
                        LearningEvent.ref_id.in_(all_sub_ids)
                    )
                ).all()
            )

        results = {}
        for m in modules:
            submodules = submodules_by_module.get(m.id, [])
            items = []
            passed_count = 0
            all_regular_passed = True
            
            for s in submodules:
                requires_quiz = bool(getattr(s, "requires_quiz", True))
                best_score = best_attempts.get(s.quiz_id) if requires_quiz else None
                is_passed = best_score is not None if requires_quiz else False
                items.append({
                    "submodule_id": str(s.id),
                    "passed": is_passed,
                    "read": s.id in read_ids
                })

                if requires_quiz:
                    if is_passed:
                        passed_count += 1
                    else:
                        all_regular_passed = False
                else:
                    # materials-only lesson: completion is read confirmation
                    if s.id not in read_ids:
                        all_regular_passed = False

            final_best_score = best_attempts.get(m.final_quiz_id) if m.final_quiz_id else None
            final_passed = final_best_score is not None
            total_steps = len(submodules) + (1 if m.final_quiz_id else 0)
            completed = all_regular_passed and (not m.final_quiz_id or final_passed)

            results[m.id] = {
                "total": total_steps,
                "passed": passed_count + (1 if final_passed else 0),
                "completed": completed,
                "submodules": items
            }
        
        return results

    def get_modules_analytics_batch(self, module_id: uuid.UUID) -> List[Dict[str, Any]]:
        """
        Batch analytics calculation for all users in a module.
        Eliminates N+1 query patterns.
        """
        submodules = self.db.scalars(
            select(Submodule).where(Submodule.module_id == module_id).order_by(Submodule.order)
        ).all()
        if not submodules:
            return []

        quiz_ids = [s.quiz_id for s in submodules]
        m = self.db.scalar(select(Module).where(Module.id == module_id))
        if m and m.final_quiz_id:
            quiz_ids.append(m.final_quiz_id)

        users = self.db.scalars(select(User).order_by(User.name)).all()
        user_ids = [u.id for u in users]

        # Batch load all passed attempts for all users/quizzes
        passed_attempts_rows = self.db.execute(
            select(QuizAttempt.user_id, QuizAttempt.quiz_id)
            .where(
                QuizAttempt.user_id.in_(user_ids),
                QuizAttempt.quiz_id.in_(quiz_ids),
                QuizAttempt.passed == True
            )
        ).all()
        
        passed_map = {} # (user_id, quiz_id) -> bool
        for uid, qid in passed_attempts_rows:
            passed_map[(uid, qid)] = True

        # Batch load all read events
        sub_ids = [s.id for s in submodules]
        read_events_rows = self.db.execute(
            select(LearningEvent.user_id, LearningEvent.ref_id)
            .where(
                LearningEvent.user_id.in_(user_ids),
                LearningEvent.type == LearningEventType.submodule_opened,
                LearningEvent.meta == "read",
                LearningEvent.ref_id.in_(sub_ids)
            )
        ).all()
        
        read_map = {} # (user_id, submodule_id) -> bool
        for uid, sid in read_events_rows:
            read_map[(uid, sid)] = True

        report = []
        for u in users:
            read_count = sum(1 for s in submodules if (u.id, s.id) in read_map)
            passed_quiz_count = sum(1 for s in submodules if (u.id, s.quiz_id) in passed_map)
            
            final_passed = False
            if m and m.final_quiz_id:
                final_passed = (u.id, m.final_quiz_id) in passed_map

            total_lessons = len(submodules)
            completed = (passed_quiz_count == total_lessons) and (not m or not m.final_quiz_id or final_passed)

            report.append({
                "user_id": str(u.id),
                "name": u.name,
                "role": u.role.value,
                "read_count": read_count,
                "passed_count": passed_quiz_count,
                "total_lessons": total_lessons,
                "final_passed": final_passed,
                "completed": completed,
                "last_activity": u.last_activity_at.isoformat() if u.last_activity_at else None
            })
        
        return report

    def get_module_progress(self, user: User, module_id: uuid.UUID) -> Dict[str, Any] | None:
        """
        Единый источник правды для прогресса по модулю.
        Рассчитывает состояния всех подмодулей и общие показатели.
        """
        m = self.db.scalar(select(Module).where(Module.id == module_id))
        if not m:
            return None

        submodules = self.db.scalars(
            select(Submodule).where(Submodule.module_id == m.id).order_by(Submodule.order)
        ).all()
        
        if not submodules:
            return {
                "module_id": str(m.id),
                "title": m.title,
                "total": 0,
                "passed": 0,
                "final_submodule_id": None,
                "final_quiz_id": str(m.final_quiz_id) if m.final_quiz_id else None,
                "final_passed": False,
                "final_best_score": None,
                "completed": False,
                "submodules": []
            }

        quiz_ids = [s.quiz_id for s in submodules if bool(getattr(s, "requires_quiz", True))]
        if m.final_quiz_id:
            quiz_ids.append(m.final_quiz_id)
        
        # Batch load quiz results
        best_attempts = dict(
            self.db.execute(
                select(QuizAttempt.quiz_id, func.max(QuizAttempt.score))
                .where(
                    QuizAttempt.user_id == user.id, 
                    QuizAttempt.quiz_id.in_(quiz_ids), 
                    QuizAttempt.passed == True
                )
                .group_by(QuizAttempt.quiz_id)
            ).all()
        )

        # Last attempt per quiz (for persistent UI display, even if not passed)
        rn = func.row_number().over(
            partition_by=QuizAttempt.quiz_id,
            order_by=(desc(QuizAttempt.finished_at), desc(QuizAttempt.id)),
        ).label("rn")

        last_attempt_subq = (
            select(
                QuizAttempt.quiz_id.label("quiz_id"),
                QuizAttempt.score.label("score"),
                QuizAttempt.passed.label("passed"),
                QuizAttempt.finished_at.label("finished_at"),
                rn,
            )
            .where(QuizAttempt.user_id == user.id, QuizAttempt.quiz_id.in_(quiz_ids))
            .subquery()
        )

        last_attempt_rows = self.db.execute(
            select(
                last_attempt_subq.c.quiz_id,
                last_attempt_subq.c.score,
                last_attempt_subq.c.passed,
            ).where(last_attempt_subq.c.rn == 1)
        ).all()

        last_attempt_map: dict[uuid.UUID, dict[str, Any]] = {
            quiz_id: {
                "score": int(score) if score is not None else None,
                "passed": bool(passed) if passed is not None else None,
            }
            for quiz_id, score, passed in last_attempt_rows
        }

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

        # Батч-загрузка подтверждений прочтения.
        # Important: meta can be legacy 'read' OR JSON like {"action":"read"}.
        sub_ids = [s.id for s in submodules]
        read_rows = self.db.execute(
            select(LearningEvent.ref_id, LearningEvent.meta).where(
                LearningEvent.user_id == user.id,
                LearningEvent.type == LearningEventType.submodule_opened,
                LearningEvent.meta.is_not(None),
                LearningEvent.ref_id.in_(sub_ids),
            )
        ).all()
        read_ids = {ref_id for (ref_id, meta) in (read_rows or []) if _meta_action_is_read(meta)}

        items = []
        passed_count = 0
        all_regular_passed = True
        
        for s in submodules:
            requires_quiz = bool(getattr(s, "requires_quiz", True))
            best_score = best_attempts.get(s.quiz_id) if requires_quiz else None
            is_passed = best_score is not None if requires_quiz else False
            is_read = s.id in read_ids

            last = last_attempt_map.get(s.quiz_id) or {}
            last_score = last.get("score")
            last_passed = last.get("passed")
            
            # Логика блокировки: последовательное прохождение
            locked = bool(not all_regular_passed and items)
            locked_reason = "complete_previous_lesson" if locked else None

            items.append({
                "submodule_id": str(s.id),
                "quiz_id": str(s.quiz_id),
                "requires_quiz": bool(requires_quiz),
                "title": s.title,
                "order": s.order,
                "read": bool(is_read),
                "passed": is_passed,
                "best_score": int(best_score) if best_score is not None else None,
                "last_score": last_score,
                "last_passed": last_passed,
                "locked": locked,
                "locked_reason": locked_reason,
                "is_final": False
            })

            if requires_quiz:
                if is_passed:
                    passed_count += 1
                else:
                    all_regular_passed = False
            else:
                # materials-only lesson: completion is read confirmation
                if is_read:
                    passed_count += 1
                else:
                    all_regular_passed = False

        total_steps = len(submodules) + (1 if m.final_quiz_id else 0)
        final_quiz_id_str = str(m.final_quiz_id) if m.final_quiz_id else None
        final_best_score = best_attempts.get(m.final_quiz_id) if m.final_quiz_id else None
        final_passed = final_best_score is not None
        
        completed = all_regular_passed and (not m.final_quiz_id or final_passed)
        
        return {
            "module_id": str(m.id),
            "title": m.title,
            "total": total_steps,
            "passed": passed_count + (1 if final_passed else 0),
            "final_submodule_id": None,
            "final_quiz_id": final_quiz_id_str,
            "final_passed": final_passed,
            "final_best_score": int(final_best_score) if final_best_score is not None else None,
            "completed": completed,
            "submodules": items
        }


