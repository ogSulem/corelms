"""Consistent, batched progress for the catalog, lessons and admin analytics.

Current coverage and an earned completion are different facts. Content changes
may change coverage, but can never revoke an earned completion or quiz result.
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.asset import ContentAsset
from app.models.attempt import QuizAttempt
from app.models.audit import LearningEvent, LearningEventType
from app.models.completion import LessonQuizVersion, ModuleCompletion
from app.models.module import Module, Submodule
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.user import User


def is_read_meta(meta: str | None) -> bool:
    if str(meta or "").strip().lower() == "read":
        return True
    try:
        obj = json.loads(meta or "")
        return isinstance(obj, dict) and str(obj.get("action", "")).lower() == "read"
    except (TypeError, ValueError):
        return False


def remember_quiz_version(db: Session, sub: Submodule) -> None:
    if sub.quiz_id and db.get(LessonQuizVersion, sub.quiz_id) is None:
        db.add(LessonQuizVersion(quiz_id=sub.quiz_id, submodule_id=sub.id))
        db.flush()


class LearningService:
    def __init__(self, db: Session):
        self.db = db

    _meta_action_is_read = staticmethod(is_read_meta)

    def _calculate(self, users: list[User], modules: list[Module], *, compact: bool = False) -> dict[tuple[uuid.UUID, uuid.UUID], dict[str, Any]]:
        if not users or not modules:
            return {}
        mids, uids = [m.id for m in modules], [u.id for u in users]
        subs = list(self.db.scalars(select(Submodule).where(
            Submodule.module_id.in_(mids), Submodule.is_archived.is_(False)
        ).order_by(Submodule.order)))
        lesson_ids = [s.id for s in subs if not s.is_folder]
        lessons_by_module: dict[uuid.UUID, list[Submodule]] = defaultdict(list)
        quiz_to_lesson: dict[uuid.UUID, uuid.UUID] = {}
        for sub in subs:
            if not sub.is_folder:
                lessons_by_module[sub.module_id].append(sub)
                quiz_to_lesson[sub.quiz_id] = sub.id
        for qid, sid in self.db.execute(select(LessonQuizVersion.quiz_id, LessonQuizVersion.submodule_id).where(
            LessonQuizVersion.submodule_id.in_(lesson_ids)
        )):
            quiz_to_lesson[qid] = sid

        quiz_ids = set(quiz_to_lesson) | {m.final_quiz_id for m in modules if m.final_quiz_id}
        best: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
        last: dict[tuple[uuid.UUID, uuid.UUID], QuizAttempt] = {}
        for attempt in self.db.scalars(select(QuizAttempt).where(
            QuizAttempt.user_id.in_(uids), QuizAttempt.quiz_id.in_(quiz_ids), QuizAttempt.finished_at.is_not(None)
        ).order_by(QuizAttempt.finished_at, QuizAttempt.id)):
            # Lesson identity is stable even when questions are regenerated.
            ref = quiz_to_lesson.get(attempt.quiz_id, attempt.quiz_id)
            key = (attempt.user_id, ref)
            last[key] = attempt
            if attempt.passed:
                best[key] = max(best.get(key, 0), int(attempt.score or 0))

        reads: set[tuple[uuid.UUID, uuid.UUID]] = set()
        opened: set[tuple[uuid.UUID, uuid.UUID]] = set()
        viewed_revisions: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
        events = self.db.execute(select(LearningEvent.user_id, LearningEvent.ref_id, LearningEvent.meta).where(
            LearningEvent.user_id.in_(uids), LearningEvent.type == LearningEventType.submodule_opened,
            or_(LearningEvent.ref_id.in_(lesson_ids), LearningEvent.ref_id.is_(None))
        ))
        for uid, ref, meta in events:
            if ref is not None and is_read_meta(meta):
                reads.add((uid, ref))
            elif ref is None:
                try:
                    data = json.loads(meta or "")
                    if isinstance(data, dict) and data.get("action") == "module_open":
                        key = (uid, uuid.UUID(str(data.get("module_id"))))
                        opened.add(key)
                        viewed_revisions[key] = max(viewed_revisions.get(key, 0), int(data.get("content_revision") or 0))
                except (TypeError, ValueError):
                    pass

        # Empty modules must not be considered completed. Folder/file-only modules
        # retain the established "open materials" rule, without a 200-event cutoff.
        has_assets = set(self.db.scalars(select(ContentAsset.module_id).where(
            ContentAsset.module_id.in_(mids), ContentAsset.is_archived.is_(False),
            ~ContentAsset.id.in_(select(SubmoduleAssetMap.asset_id))
        ).distinct()))
        has_assets.update(self.db.scalars(select(Submodule.module_id)
            .join(SubmoduleAssetMap, SubmoduleAssetMap.submodule_id == Submodule.id)
            .join(ContentAsset, ContentAsset.id == SubmoduleAssetMap.asset_id)
            .where(Submodule.module_id.in_(mids), Submodule.is_archived.is_(False), ContentAsset.is_archived.is_(False))
            .distinct()))
        earned = {(c.user_id, c.module_id): c for c in self.db.scalars(select(ModuleCompletion).where(
            ModuleCompletion.user_id.in_(uids), ModuleCompletion.module_id.in_(mids)
        ))}
        result = {}
        for user in users:
            for module in modules:
                lessons = lessons_by_module[module.id]
                items = []
                completed_lessons = read_count = 0
                for sub in lessons:
                    key = (user.id, sub.id)
                    score = best.get(key)
                    is_read = key in reads
                    passed = score is not None
                    completed = passed if sub.requires_quiz else is_read
                    read_count += int(is_read)
                    completed_lessons += int(completed)
                    latest = last.get(key)
                    if not compact:
                        items.append({
                            "submodule_id": str(sub.id), "quiz_id": str(sub.quiz_id),
                            "title": sub.title, "order": sub.order, "requires_quiz": sub.requires_quiz,
                            "read": is_read, "passed": passed, "completed": completed,
                            "best_score": score, "last_score": latest.score if latest else None,
                            "last_passed": latest.passed if latest else None,
                            # Materials are freely accessible. Starting a quiz still requires reading.
                            "locked": False, "locked_reason": None, "is_final": False,
                        })
                final_id = module.final_quiz_id if module.final_quiz_enabled and any(s.requires_quiz for s in lessons) else None
                final_score = best.get((user.id, final_id)) if final_id else None
                final_passed = final_score is not None
                total = len(lessons) + int(final_id is not None)
                passed_count = completed_lessons + int(final_passed)
                current_completed = bool(lessons and completed_lessons == len(lessons) and (not final_id or final_passed))
                if not lessons:
                    current_completed = module.id in has_assets and (user.id, module.id) in opened
                achievement = earned.get((user.id, module.id))
                result[(user.id, module.id)] = {
                    "module_id": str(module.id), "title": module.title,
                    "total": total, "passed": passed_count, "read_count": read_count,
                    "total_lessons": total, "passed_count": passed_count,
                    "final_submodule_id": None, "final_quiz_id": str(final_id) if final_id else None,
                    "final_passed": final_passed, "final_best_score": final_score,
                    "completed": bool(achievement or current_completed), "current_completed": current_completed,
                    "completed_at": achievement.completed_at.isoformat() if achievement else None,
                    "completed_revision": achievement.content_revision if achievement else None,
                    "content_revision": module.content_revision,
                    "has_materials": bool(lessons or module.id in has_assets),
                    "has_updates": bool(achievement and (not current_completed or module.content_revision > max(
                        achievement.content_revision, viewed_revisions.get((user.id, module.id), 0)))),
                    "submodules": items,
                }
        return result

    def get_modules_progress(self, user: User, module_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        modules = list(self.db.scalars(select(Module).where(Module.id.in_(module_ids))))
        return {mid: value for (_, mid), value in self._calculate([user], modules).items()}

    def get_modules_progress_compact(self, user: User, module_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        # No stale 45-second progress cache after read/submit/content updates.
        modules = list(self.db.scalars(select(Module).where(Module.id.in_(module_ids))))
        return {mid: {k: v for k, v in value.items() if k != "submodules"}
                for (_, mid), value in self._calculate([user], modules, compact=True).items()}

    def get_progress_matrix(self, users: list[User], modules: list[Module]) -> dict:
        """Batched compact reporting: do not duplicate the lifecycle rules in admin."""
        return self._calculate(users, modules, compact=True)

    def get_module_progress(self, user: User, module_id: uuid.UUID) -> dict[str, Any] | None:
        return self.get_modules_progress(user, [module_id]).get(module_id)

    def get_modules_analytics_batch(self, module_id: uuid.UUID) -> list[dict[str, Any]]:
        module = self.db.get(Module, module_id)
        if module is None:
            return []
        users = list(self.db.scalars(select(User).order_by(User.name)))
        results = self._calculate(users, [module], compact=True)
        return [{
            **results[(u.id, module.id)], "user_id": str(u.id), "name": u.name,
            "role": u.role.value, "last_activity": u.last_activity_at.isoformat() if u.last_activity_at else None,
        } for u in users]

    def remember_completions(self, module: Module, user: User | None = None) -> int:
        """Called inside the same transaction BEFORE an edit / AFTER read or submit.

        Writers lock the module row first, so an edit cannot race a learner's final
        action. This also lazily preserves pre-migration file-only achievements.
        """
        self.db.flush()
        users = [user] if user else list(self.db.scalars(select(User)))
        results = self._calculate(users, [module], compact=True)
        count = 0
        for learner in users:
            p = results[(learner.id, module.id)]
            if p["current_completed"] and p["completed_at"] is None:
                self.db.add(ModuleCompletion(
                    user_id=learner.id, module_id=module.id,
                    completed_at=datetime.now(timezone.utc), content_revision=module.content_revision,
                ))
                count += 1
        self.db.flush()
        return count
