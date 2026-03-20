from __future__ import annotations

import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session
import json

from app.core.redis_client import get_redis
from app.models.module import Module, ModuleSkillMap, Submodule
from app.models.attempt import QuizAttempt
from app.models.audit import LearningEvent, LearningEventType
from app.models.user import User

class LearningService:
    def __init__(self, db: Session):
        self.db = db

    def _meta_action_is_read(self, meta: str | None) -> bool:
        if not meta:
            return False
        action = str(meta).strip().lower()
        if action == "read":
            return True
        try:
            obj = json.loads(str(meta))
            if isinstance(obj, dict):
                act = str(obj.get("action") or "").strip().lower()
                if act == "read":
                    return True
        except Exception:
            return False
        return False

    def get_modules_progress_compact(self, user: User, module_ids: List[uuid.UUID]) -> Dict[uuid.UUID, Dict[str, Any]]:
        """Fast progress aggregation for modules list.

        Unlike get_modules_progress(), this method does NOT return per-submodule items.
        It is intended for /modules/overview to keep first-load latency low.
        """

        if not module_ids:
            return {}

        # Short cache to speed up cold loads, while still staying near-real-time.
        cache_key = None
        try:
            mids = ",".join(sorted(str(x) for x in module_ids))
            cache_key = f"progress:modules_compact:v1:{str(user.id)}:{mids}"
            r = get_redis()
            cached = r.get(cache_key)
            if cached:
                obj = json.loads(cached)
                if isinstance(obj, dict):
                    out: dict[uuid.UUID, dict[str, Any]] = {}
                    for k, v in obj.items():
                        try:
                            mid = uuid.UUID(str(k))
                        except Exception:
                            continue
                        if isinstance(v, dict):
                            out[mid] = v
                    return out
        except Exception:
            cache_key = None

        def _meta_action_is_read(meta: str | None) -> bool:
            if not meta:
                return False
            action = str(meta).strip().lower()
            if action == "read":
                return True
            try:
                obj = json.loads(str(meta))
                if isinstance(obj, dict):
                    act = str(obj.get("action") or "").strip().lower()
                    if act == "read":
                        return True
            except Exception:
                return False
            return False

        # Fetch only fields needed.
        module_rows = self.db.execute(
            select(Module.id, Module.final_quiz_id).where(Module.id.in_(module_ids))
        ).all()
        final_quiz_by_module: dict[uuid.UUID, uuid.UUID | None] = {mid: fq for (mid, fq) in (module_rows or [])}

        sub_rows = self.db.execute(
            select(
                Submodule.module_id,
                Submodule.id,
                Submodule.quiz_id,
                Submodule.requires_quiz,
                Submodule.is_folder,
            )
            .where(Submodule.module_id.in_(module_ids))
            .order_by(Submodule.module_id, Submodule.order)
        ).all()

        subs_by_module: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID | None, bool]]] = {}
        all_quiz_ids: set[uuid.UUID] = set()
        all_sub_ids: list[uuid.UUID] = []

        for mid, sid, qid, requires_quiz, is_folder in (sub_rows or []):
            if bool(is_folder):
                continue
            rq = bool(requires_quiz) if requires_quiz is not None else True
            subs_by_module.setdefault(mid, []).append((sid, qid, rq))
            all_sub_ids.append(sid)
            if rq and qid is not None:
                all_quiz_ids.add(qid)

        # Final quiz participates only if the module has at least one quiz-required lesson.
        for mid, subs in subs_by_module.items():
            any_quiz_required = any(rq for (_sid, _qid, rq) in subs)
            fq = final_quiz_by_module.get(mid)
            if any_quiz_required and fq is not None:
                all_quiz_ids.add(fq)

        passed_quiz_ids: set[uuid.UUID] = set()
        if all_quiz_ids:
            rows = self.db.execute(
                select(QuizAttempt.quiz_id)
                .where(
                    QuizAttempt.user_id == user.id,
                    QuizAttempt.quiz_id.in_(list(all_quiz_ids)),
                    QuizAttempt.passed == True,  # noqa: E712
                )
                .group_by(QuizAttempt.quiz_id)
            ).all()
            passed_quiz_ids = {qid for (qid,) in (rows or []) if qid is not None}

        read_ids: set[uuid.UUID] = set()
        if all_sub_ids:
            read_rows = self.db.execute(
                select(LearningEvent.ref_id, LearningEvent.meta).where(
                    LearningEvent.user_id == user.id,
                    LearningEvent.type == LearningEventType.submodule_opened,
                    LearningEvent.meta.is_not(None),
                    LearningEvent.ref_id.in_(all_sub_ids),
                )
            ).all()
            read_ids = {ref_id for (ref_id, meta) in (read_rows or []) if ref_id is not None and _meta_action_is_read(meta)}

        results: dict[uuid.UUID, dict[str, Any]] = {}
        for mid in module_ids:
            subs = subs_by_module.get(mid, [])
            if not subs:
                results[mid] = {
                    "total_lessons": 0,
                    "passed_count": 0,
                    "read_count": 0,
                    "final_passed": False,
                    "completed": False,
                }
                continue

            any_quiz_required = any(rq for (_sid, _qid, rq) in subs)
            fq = final_quiz_by_module.get(mid) if any_quiz_required else None
            final_passed = bool(fq is not None and fq in passed_quiz_ids)

            read_count = 0
            passed_lessons = 0
            all_regular_passed = True

            for sid, qid, rq in subs:
                is_read = sid in read_ids
                if is_read:
                    read_count += 1

                if rq:
                    is_passed = bool(qid is not None and qid in passed_quiz_ids)
                    if is_passed:
                        passed_lessons += 1
                    else:
                        all_regular_passed = False
                else:
                    # materials-only lesson
                    if is_read:
                        passed_lessons += 1
                    else:
                        all_regular_passed = False

            total_steps = len(subs) + (1 if fq is not None else 0)
            passed_total = passed_lessons + (1 if final_passed else 0)
            completed = bool(all_regular_passed and (fq is None or final_passed))

            results[mid] = {
                "total_lessons": int(total_steps),
                "passed_count": int(passed_total),
                "read_count": int(read_count),
                "final_passed": bool(final_passed),
                "completed": bool(completed),
            }

        if cache_key:
            try:
                r = get_redis()
                payload = {str(k): v for k, v in results.items()}
                r.setex(cache_key, 45, json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass

        return results

    def get_modules_progress(self, user: User, module_ids: List[uuid.UUID]) -> Dict[uuid.UUID, Dict[str, Any]]:
        """
        Batch source of truth for progress calculation.
        """
        if not module_ids:
            return {}

        def _meta_action_is_read(meta: str | None) -> bool:
            if not meta:
                return False
            action = str(meta).strip().lower()
            if action == "read":
                return True
            try:
                obj = json.loads(str(meta))
                if isinstance(obj, dict):
                    act = str(obj.get("action") or "").strip().lower()
                    if act == "read":
                        return True
            except Exception:
                return False
            return False

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
            # Outline folders are UI-only and must not affect progress totals or final exam gating.
            if bool(getattr(s, "is_folder", False)):
                continue
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
        read_ids: set[uuid.UUID] = set()
        if all_sub_ids:
            read_rows = self.db.execute(
                select(LearningEvent.ref_id, LearningEvent.meta).where(
                    LearningEvent.user_id == user.id,
                    LearningEvent.type == LearningEventType.submodule_opened,
                    LearningEvent.meta.is_not(None),
                    LearningEvent.ref_id.in_(all_sub_ids),
                )
            ).all()
            read_ids = {ref_id for (ref_id, meta) in (read_rows or []) if _meta_action_is_read(meta)}

        results = {}
        for m in modules:
            submodules = submodules_by_module.get(m.id, [])
            items = []
            passed_count = 0
            all_regular_passed = True
            any_quiz_required = False
            
            for s in submodules:
                requires_quiz = bool(getattr(s, "requires_quiz", True))
                if requires_quiz:
                    any_quiz_required = True
                best_score = best_attempts.get(s.quiz_id) if requires_quiz else None
                is_passed = best_score is not None if requires_quiz else False
                is_read = s.id in read_ids
                items.append({
                    "submodule_id": str(s.id),
                    "passed": is_passed,
                    "read": is_read
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

            effective_final_quiz_id = m.final_quiz_id if (m.final_quiz_id and any_quiz_required) else None
            final_best_score = best_attempts.get(effective_final_quiz_id) if effective_final_quiz_id else None
            final_passed = final_best_score is not None
            total_steps = len(submodules) + (1 if effective_final_quiz_id else 0)
            completed = all_regular_passed and (not effective_final_quiz_id or final_passed)

            results[m.id] = {
                "total": total_steps,
                "passed": passed_count + (1 if final_passed else 0),
                "completed": completed,
                "submodules": items,
                "final_quiz_id": str(effective_final_quiz_id) if effective_final_quiz_id else None,
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
        submodules = [s for s in (submodules or []) if not bool(getattr(s, "is_folder", False))]
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

        # Batch load all read/open events (legacy + JSON meta)
        sub_ids = [s.id for s in submodules]
        read_events_rows = self.db.execute(
            select(LearningEvent.user_id, LearningEvent.ref_id, LearningEvent.meta)
            .where(
                LearningEvent.user_id.in_(user_ids),
                LearningEvent.type == LearningEventType.submodule_opened,
                LearningEvent.meta.is_not(None),
                LearningEvent.ref_id.in_(sub_ids),
            )
        ).all()

        read_map = {}  # (user_id, submodule_id) -> bool
        for uid, sid, meta in (read_events_rows or []):
            if sid is None:
                continue
            if self._meta_action_is_read(meta):
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
        submodules = [s for s in (submodules or []) if not bool(getattr(s, "is_folder", False))]
        
        if not submodules:
            # Assets-only module: allow completion via module open or any module-level asset view.
            # We intentionally do NOT introduce a new LearningEventType (would require enum migration).
            # Instead:
            # - module open: LearningEventType.submodule_opened with ref_id=None and meta {action:"module_open", module_id}
            # - asset view: LearningEventType.asset_viewed with meta containing module_id (resolved in assets router)
            opened = False
            try:
                rows = self.db.scalars(
                    select(LearningEvent)
                    .where(LearningEvent.user_id == user.id)
                    .where(LearningEvent.type.in_([LearningEventType.submodule_opened, LearningEventType.asset_viewed]))
                    .order_by(LearningEvent.created_at.desc())
                    .limit(200)
                ).all()
                for ev in rows or []:
                    try:
                        if ev.type == LearningEventType.submodule_opened:
                            meta_raw = str(ev.meta or "")
                            if not meta_raw:
                                continue
                            try:
                                obj = json.loads(meta_raw)
                            except Exception:
                                obj = None
                            if isinstance(obj, dict):
                                if str(obj.get("action") or "").strip().lower() == "module_open" and str(obj.get("module_id") or "") == str(m.id):
                                    opened = True
                                    break
                        if ev.type == LearningEventType.asset_viewed:
                            meta_raw = str(ev.meta or "")
                            if not meta_raw:
                                continue
                            try:
                                obj = json.loads(meta_raw)
                            except Exception:
                                obj = None
                            if isinstance(obj, dict) and str(obj.get("module_id") or "") == str(m.id):
                                opened = True
                                break
                    except Exception:
                        continue
            except Exception:
                opened = False

            return {
                "module_id": str(m.id),
                "title": m.title,
                "total": 0,
                "passed": 0,
                "final_submodule_id": None,
                "final_quiz_id": None,
                "final_passed": False,
                "final_best_score": None,
                "completed": bool(opened),
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
        all_quiz_passed_so_far = True
        any_quiz_required = False
        
        for s in submodules:
            requires_quiz = bool(getattr(s, "requires_quiz", True))
            if requires_quiz:
                any_quiz_required = True
            best_score = best_attempts.get(s.quiz_id) if requires_quiz else None
            is_passed = best_score is not None if requires_quiz else False
            is_read = s.id in read_ids

            last = last_attempt_map.get(s.quiz_id) or {}
            last_score = last.get("score")
            last_passed = last.get("passed")
            
            # Логика блокировки: последовательное прохождение
            locked = bool(requires_quiz and (not all_quiz_passed_so_far) and items)
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
                    all_quiz_passed_so_far = False
            else:
                # materials-only lesson: completion is read confirmation
                if is_read:
                    passed_count += 1
                else:
                    all_regular_passed = False

        effective_final_quiz_id = m.final_quiz_id if (m.final_quiz_id and any_quiz_required) else None
        total_steps = len(submodules) + (1 if effective_final_quiz_id else 0)
        final_quiz_id_str = str(effective_final_quiz_id) if effective_final_quiz_id else None
        final_best_score = best_attempts.get(effective_final_quiz_id) if effective_final_quiz_id else None
        final_passed = final_best_score is not None
        
        completed = all_regular_passed and (not effective_final_quiz_id or final_passed)
        
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


