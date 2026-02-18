from __future__ import annotations

import json
from fastapi import APIRouter, Depends, Query
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.attempt import QuizAttempt
from app.models.assignment import Assignment
from app.models.audit import LearningEvent
from app.models.asset import ContentAsset
from app.models.module import Module, Submodule
from app.models.security_audit import SecurityAuditEvent
from app.models.user import User
from app.schemas.me import (
    MyActivityFeedResponse,
    MyAssignmentsResponse,
    HistoryResponse,
    MyProfileResponse,
    MyRecentActivityResponse,
)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/profile", response_model=MyProfileResponse)
def my_profile(user: User = Depends(get_current_user)):
    role = "admin" if user.role.value == "admin" else "user"
    return {
        "id": str(user.id),
        "name": user.name,
        "role": role,
        "position": user.position,
        "xp": int(user.xp),
        "level": int(user.level),
        "streak": int(user.streak),
        "last_activity_at": user.last_activity_at.isoformat() if user.last_activity_at else None,
    }


@router.get("/activity-feed", response_model=MyActivityFeedResponse)
def my_activity_feed(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    kinds: str | None = Query(default=None),
):
    # Use the enriched recent-activity data as a source of truth
    data = my_recent_activity(db=db, user=user)

    allowed_kinds = None
    if kinds:
        allowed_kinds = {k.strip() for k in kinds.split(",") if k.strip()}

    items: list[dict] = []

    # Attempts -> single grouped element
    for a in data.get("attempts", [])[:20]:
        is_finished = bool(a.get("finished_at"))
        title = "Тест завершён" if is_finished else "Тест в процессе"
        if is_finished:
            status = "засчитан" if a.get("passed") else "не засчитан"
        else:
            status = "в процессе"

        duration_seconds = None
        try:
            if a.get("started_at") and a.get("finished_at"):
                started = datetime.fromisoformat(str(a.get("started_at")))
                finished = datetime.fromisoformat(str(a.get("finished_at")))
                duration_seconds = int(max(0, (finished - started).total_seconds()))
        except Exception:
            duration_seconds = None
        subtitle_parts = []
        if a.get("module_title"):
            subtitle_parts.append(str(a.get("module_title")))
        if a.get("submodule_title"):
            subtitle_parts.append(str(a.get("submodule_title")))
        subtitle = " · ".join(subtitle_parts) if subtitle_parts else None

        item = {
            "kind": "quiz_attempt",
            "created_at": a.get("finished_at") or a.get("started_at"),
            "title": title,
            "subtitle": subtitle,
            "status": status,
            "score": a.get("score"),
            "passed": a.get("passed"),
            "count": None,
            "duration_seconds": duration_seconds,
            "module_id": a.get("module_id"),
            "module_title": a.get("module_title"),
            "submodule_id": a.get("submodule_id"),
            "submodule_title": a.get("submodule_title"),
            "href": a.get("href"),
        }

        if (allowed_kinds is None) or (item["kind"] in allowed_kinds):
            items.append(item)

    # Events: keep only non-quiz events to avoid duplicates
    for e in data.get("events", [])[:80]:
        if e.get("type") in ("quiz_started", "quiz_completed"):
            continue
        title = e.get("title") or "Событие"
        subtitle = e.get("asset_name") or e.get("subtitle")
        if not subtitle:
            subtitle_parts = []
            if e.get("module_title"):
                subtitle_parts.append(str(e.get("module_title")))
            if e.get("submodule_title"):
                subtitle_parts.append(str(e.get("submodule_title")))
            subtitle = " · ".join(subtitle_parts) if subtitle_parts else None

        kind = "asset" if e.get("asset_id") else "lesson"
        item = {
            "kind": kind,
            "created_at": e.get("created_at"),
            "title": title,
            "subtitle": subtitle,
            "status": None,
            "score": None,
            "passed": None,
            "count": None,
            "duration_seconds": None,
            "module_id": e.get("module_id"),
            "module_title": e.get("module_title"),
            "submodule_id": e.get("submodule_id"),
            "submodule_title": e.get("submodule_title"),
            "href": e.get("href"),
        }

        if (allowed_kinds is None) or (item["kind"] in allowed_kinds):
            items.append(item)

    # Sort by created_at desc
    def _sort_key(x: dict) -> str:
        return str(x.get("created_at") or "")

    items.sort(key=_sort_key, reverse=True)

    # Deduplicate: collapse repeated identical items near each other
    grouped: list[dict] = []
    for it in items:
        if not grouped:
            grouped.append(it)
            continue

        prev = grouped[-1]
        same_identity = (
            prev.get("kind") == it.get("kind")
            and prev.get("title") == it.get("title")
            and prev.get("subtitle") == it.get("subtitle")
            and prev.get("href") == it.get("href")
        )

        if same_identity and it.get("kind") != "quiz_attempt":
            prev["count"] = int(prev.get("count") or 1) + 1
            if str(it.get("created_at") or "") > str(prev.get("created_at") or ""):
                prev["created_at"] = it.get("created_at")
            continue

        grouped.append(it)

    return {"items": grouped[:30]}


@router.get("/assignments", response_model=MyAssignmentsResponse)
def my_assignments(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Assignment).where(Assignment.assigned_to == user.id).order_by(Assignment.created_at.desc())).all()
    return {
        "items": [
            {
                "id": str(a.id),
                "type": a.type.value,
                "target_id": str(a.target_id),
                "status": a.status.value,
                "priority": a.priority,
                "deadline": a.deadline.isoformat() if a.deadline else None,
            }
            for a in rows
        ]
    }


@router.get("/recent-activity", response_model=MyRecentActivityResponse)
def my_recent_activity(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    attempts = db.scalars(
        select(QuizAttempt)
        .where(QuizAttempt.user_id == user.id)
        .order_by(QuizAttempt.started_at.desc())
        .limit(10)
    ).all()
    events = db.scalars(
        select(LearningEvent)
        .where(LearningEvent.user_id == user.id)
        .order_by(LearningEvent.created_at.desc())
        .limit(20)
    ).all()

    # Bulk enrich attempts with module/submodule
    attempt_quiz_ids = list({a.quiz_id for a in attempts if a.quiz_id is not None})
    subs_by_quiz: dict[str, dict] = {}
    if attempt_quiz_ids:
        rows = db.execute(
            select(Submodule.quiz_id, Submodule.id, Submodule.title, Module.id, Module.title)
            .select_from(Submodule)
            .join(Module, Module.id == Submodule.module_id)
            .where(Submodule.quiz_id.in_(attempt_quiz_ids))
        ).all()
        for quiz_id, sub_id, sub_title, mod_id, mod_title in rows:
            subs_by_quiz[str(quiz_id)] = {
                "submodule_id": str(sub_id),
                "submodule_title": str(sub_title),
                "module_id": str(mod_id),
                "module_title": str(mod_title),
            }

    # Bulk enrich events (submodule/quiz/asset)
    sub_ids = [e.ref_id for e in events if e.ref_id is not None and e.type.value == "submodule_opened"]
    quiz_ids = [e.ref_id for e in events if e.ref_id is not None and e.type.value in ("quiz_started", "quiz_completed")]
    asset_ids = [e.ref_id for e in events if e.ref_id is not None and e.type.value == "asset_viewed"]

    subs_by_id: dict[str, dict] = {}
    if sub_ids:
        rows = db.execute(
            select(Submodule.id, Submodule.title, Module.id, Module.title)
            .select_from(Submodule)
            .join(Module, Module.id == Submodule.module_id)
            .where(Submodule.id.in_(sub_ids))
        ).all()
        for sid, stitle, mid, mtitle in rows:
            subs_by_id[str(sid)] = {
                "submodule_id": str(sid),
                "submodule_title": str(stitle),
                "module_id": str(mid),
                "module_title": str(mtitle),
            }

    subs_by_quiz_event: dict[str, dict] = {}
    if quiz_ids:
        rows = db.execute(
            select(Submodule.quiz_id, Submodule.id, Submodule.title, Module.id, Module.title)
            .select_from(Submodule)
            .join(Module, Module.id == Submodule.module_id)
            .where(Submodule.quiz_id.in_(quiz_ids))
        ).all()
        for qid, sid, stitle, mid, mtitle in rows:
            subs_by_quiz_event[str(qid)] = {
                "submodule_id": str(sid),
                "submodule_title": str(stitle),
                "module_id": str(mid),
                "module_title": str(mtitle),
            }

    assets_by_id: dict[str, dict] = {}
    if asset_ids:
        rows = db.execute(
            select(ContentAsset.id, ContentAsset.original_filename)
            .where(ContentAsset.id.in_(asset_ids))
        ).all()
        for aid, name in rows:
            assets_by_id[str(aid)] = {"asset_id": str(aid), "asset_name": str(name)}

    def _event_title(e: LearningEvent) -> tuple[str, str | None]:
        t = e.type.value
        if t == "quiz_started":
            return ("Начат тест", "Попытка началась")
        if t == "quiz_completed":
            return ("Завершён тест", "Попытка завершена")
        if t == "asset_viewed":
            return ("Открыт материал", None)
        if t == "submodule_opened":
            if (e.meta or "").lower() == "read":
                return ("Отмечено как прочитано", "Урок")
            return ("Открыт урок", "Урок")
        return ("Событие", None)

    return {
        "attempts": [
            {
                "quiz_id": str(a.quiz_id),
                "attempt_no": int(a.attempt_no),
                "score": int(a.score) if a.score is not None else None,
                "passed": bool(a.passed),
                "started_at": a.started_at.isoformat(),
                "finished_at": a.finished_at.isoformat() if a.finished_at else None,
                "module_id": subs_by_quiz.get(str(a.quiz_id), {}).get("module_id"),
                "module_title": subs_by_quiz.get(str(a.quiz_id), {}).get("module_title"),
                "submodule_id": subs_by_quiz.get(str(a.quiz_id), {}).get("submodule_id"),
                "submodule_title": subs_by_quiz.get(str(a.quiz_id), {}).get("submodule_title"),
                "href": (
                    f"/submodules/{subs_by_quiz.get(str(a.quiz_id), {}).get('submodule_id')}?module={subs_by_quiz.get(str(a.quiz_id), {}).get('module_id')}&quiz={a.quiz_id}"
                    if subs_by_quiz.get(str(a.quiz_id), {}).get("submodule_id")
                    else None
                ),
            }
            for a in attempts
        ],
        "events": [
            {
                "type": e.type.value,
                "ref_id": str(e.ref_id) if e.ref_id else None,
                "created_at": e.created_at.isoformat(),
                "meta": e.meta,
                "title": _event_title(e)[0],
                "subtitle": _event_title(e)[1],
                "module_id": (
                    subs_by_id.get(str(e.ref_id), {}).get("module_id")
                    if e.ref_id and e.type.value == "submodule_opened"
                    else subs_by_quiz_event.get(str(e.ref_id), {}).get("module_id")
                ),
                "module_title": (
                    subs_by_id.get(str(e.ref_id), {}).get("module_title")
                    if e.ref_id and e.type.value == "submodule_opened"
                    else subs_by_quiz_event.get(str(e.ref_id), {}).get("module_title")
                ),
                "submodule_id": (
                    subs_by_id.get(str(e.ref_id), {}).get("submodule_id")
                    if e.ref_id and e.type.value == "submodule_opened"
                    else subs_by_quiz_event.get(str(e.ref_id), {}).get("submodule_id")
                ),
                "submodule_title": (
                    subs_by_id.get(str(e.ref_id), {}).get("submodule_title")
                    if e.ref_id and e.type.value == "submodule_opened"
                    else subs_by_quiz_event.get(str(e.ref_id), {}).get("submodule_title")
                ),
                "asset_id": assets_by_id.get(str(e.ref_id), {}).get("asset_id") if e.ref_id else None,
                "asset_name": assets_by_id.get(str(e.ref_id), {}).get("asset_name") if e.ref_id else None,
                "href": (
                    f"/submodules/{subs_by_id.get(str(e.ref_id), {}).get('submodule_id')}?module={subs_by_id.get(str(e.ref_id), {}).get('module_id')}"
                    if e.ref_id and e.type.value == "submodule_opened" and subs_by_id.get(str(e.ref_id), {}).get("submodule_id")
                    else (
                        f"/submodules/{subs_by_quiz_event.get(str(e.ref_id), {}).get('submodule_id')}?module={subs_by_quiz_event.get(str(e.ref_id), {}).get('module_id')}&quiz={e.ref_id}"
                        if e.ref_id and e.type.value in ("quiz_started", "quiz_completed") and subs_by_quiz_event.get(str(e.ref_id), {}).get("submodule_id")
                        else None
                    )
                ),
            }
            for e in events
        ],
    }


@router.get("/history", response_model=HistoryResponse)
def my_history(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=50),
):
    take = max(1, min(int(limit or 50), 200))

    # Pull both attempts and learning events and merge by time.
    attempts = db.scalars(
        select(QuizAttempt)
        .where(QuizAttempt.user_id == user.id)
        .order_by(QuizAttempt.started_at.desc())
        .limit(take)
    ).all()
    events = db.scalars(
        select(LearningEvent)
        .where(LearningEvent.user_id == user.id)
        .order_by(LearningEvent.created_at.desc())
        .limit(take)
    ).all()

    sec_events = db.scalars(
        select(SecurityAuditEvent)
        .where(SecurityAuditEvent.target_user_id == user.id)
        .where(SecurityAuditEvent.event_type.in_(["auth_login_new_context", "auth_login_success"]))
        .order_by(SecurityAuditEvent.created_at.desc())
        .limit(take)
    ).all()

    # Enrich attempts with module/submodule
    attempt_quiz_ids = list({a.quiz_id for a in attempts if a.quiz_id is not None})
    subs_by_quiz: dict[str, dict] = {}
    if attempt_quiz_ids:
        rows = db.execute(
            select(Submodule.quiz_id, Submodule.id, Submodule.title, Module.id, Module.title)
            .select_from(Submodule)
            .join(Module, Module.id == Submodule.module_id)
            .where(Submodule.quiz_id.in_(attempt_quiz_ids))
        ).all()
        for quiz_id, sub_id, sub_title, mod_id, mod_title in rows:
            subs_by_quiz[str(quiz_id)] = {
                "submodule_id": str(sub_id),
                "submodule_title": str(sub_title),
                "module_id": str(mod_id),
                "module_title": str(mod_title),
            }

    # Enrich events
    sub_ids = [e.ref_id for e in events if e.ref_id is not None and e.type.value == "submodule_opened"]
    quiz_ids = [e.ref_id for e in events if e.ref_id is not None and e.type.value in ("quiz_started", "quiz_completed")]
    asset_ids = [e.ref_id for e in events if e.ref_id is not None and e.type.value == "asset_viewed"]

    subs_by_id: dict[str, dict] = {}
    if sub_ids:
        rows = db.execute(
            select(Submodule.id, Submodule.title, Module.id, Module.title)
            .select_from(Submodule)
            .join(Module, Module.id == Submodule.module_id)
            .where(Submodule.id.in_(sub_ids))
        ).all()
        for sid, stitle, mid, mtitle in rows:
            subs_by_id[str(sid)] = {
                "submodule_id": str(sid),
                "submodule_title": str(stitle),
                "module_id": str(mid),
                "module_title": str(mtitle),
            }

    subs_by_quiz_event: dict[str, dict] = {}
    if quiz_ids:
        rows = db.execute(
            select(Submodule.quiz_id, Submodule.id, Submodule.title, Module.id, Module.title)
            .select_from(Submodule)
            .join(Module, Module.id == Submodule.module_id)
            .where(Submodule.quiz_id.in_(quiz_ids))
        ).all()
        for qid, sid, stitle, mid, mtitle in rows:
            subs_by_quiz_event[str(qid)] = {
                "submodule_id": str(sid),
                "submodule_title": str(stitle),
                "module_id": str(mid),
                "module_title": str(mtitle),
            }

    assets_by_id: dict[str, dict] = {}
    if asset_ids:
        rows = db.execute(
            select(ContentAsset.id, ContentAsset.original_filename)
            .where(ContentAsset.id.in_(asset_ids))
        ).all()
        for aid, name in rows:
            assets_by_id[str(aid)] = {"asset_id": str(aid), "asset_name": str(name)}

    def _try_parse_meta(meta: str | None) -> dict | None:
        if not meta:
            return None
        try:
            obj = json.loads(str(meta))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    def _ua_device_label(ua: str) -> str | None:
        s = str(ua or "").strip()
        if not s:
            return None

        low = s.lower()
        os = ""
        if "windows" in low:
            os = "Windows"
        elif "mac os x" in low or "macintosh" in low:
            os = "macOS"
        elif "android" in low:
            os = "Android"
        elif "iphone" in low or "ipad" in low or "ios" in low:
            os = "iOS"
        elif "linux" in low:
            os = "Linux"

        browser = ""
        if "edg/" in low:
            browser = "Edge"
        elif "opr/" in low or "opera" in low:
            browser = "Opera"
        elif "chrome/" in low and "chromium" not in low and "edg/" not in low and "opr/" not in low:
            browser = "Chrome"
        elif "safari/" in low and "chrome/" not in low:
            browser = "Safari"
        elif "firefox/" in low:
            browser = "Firefox"

        label = " ".join([x for x in [os, browser] if x])
        return label or None

    def _sec_event_display(e: SecurityAuditEvent) -> tuple[str, str | None]:
        meta = _try_parse_meta(e.meta)
        new_device = bool((meta or {}).get("new_device"))
        new_ip = bool((meta or {}).get("new_ip"))
        ip = str(e.ip or (meta or {}).get("ip") or "").strip()
        ua = str((meta or {}).get("user_agent") or "").strip()
        dev = _ua_device_label(ua)

        title = "Вход в аккаунт"
        if new_device and new_ip:
            title = "Вход с нового устройства и IP"
        elif new_device:
            title = "Вход с нового устройства"
        elif new_ip:
            title = "Вход с нового IP"

        parts: list[str] = []
        if ip:
            parts.append(f"IP: {ip}")
        if dev:
            parts.append(f"DEVICE: {dev}")
        subtitle = " · ".join(parts) if parts else None
        return title, subtitle

    def _event_display(e: LearningEvent) -> tuple[str, str | None, str | None, str]:
        t = e.type.value
        meta = _try_parse_meta(e.meta)
        action = str((meta or {}).get("action") or "").strip().lower() if meta else ""

        if t == "submodule_opened":
            if action == "read" or (e.meta or "").strip().lower() == "read":
                return ("lesson", "Теория подтверждена", "Отмечено как прочитано", "submodule_read")
            return ("lesson", "Открыт урок", "Просмотр", "submodule_open")
        if t == "asset_viewed":
            fname = None
            if meta and meta.get("filename"):
                fname = str(meta.get("filename"))
            if action == "view":
                return ("asset", "Открыл материал", fname, "asset")
            if action == "download":
                return ("asset", "Скачал материал", fname, "asset")
            return ("asset", "Материал", fname, "asset")
        if t == "quiz_started":
            return ("quiz", "Начат тест", None, "quiz_start")
        if t == "quiz_completed":
            if meta and meta.get("score") is not None:
                try:
                    score = int(meta.get("score"))
                    passed = bool(meta.get("passed"))
                    return ("quiz", "Завершён тест", f"{score}% · {'зачёт' if passed else 'не зачёт'}", "quiz_finish")
                except Exception:
                    pass
            return ("quiz", "Завершён тест", None, "quiz_finish")
        return ("event", "Событие", None, t)

    items: list[dict] = []

    for a in attempts:
        ctx = subs_by_quiz.get(str(a.quiz_id), {}) if a.quiz_id else {}
        is_finished = bool(a.finished_at)
        status = "в процессе"
        if is_finished:
            status = "засчитан" if bool(a.passed) else "не засчитан"
        duration_seconds = None
        try:
            if a.started_at and a.finished_at:
                duration_seconds = int(max(0, (a.finished_at - a.started_at).total_seconds()))
        except Exception:
            duration_seconds = None
        items.append(
            {
                "id": f"attempt:{a.id}",
                "created_at": a.finished_at.isoformat() if a.finished_at else a.started_at.isoformat(),
                "kind": "quiz_attempt",
                "title": "Тест завершён" if a.finished_at else "Тест в процессе",
                "subtitle": (
                    f"{int(a.score)}% · {'зачёт' if a.passed else 'не зачёт'}" if a.score is not None else None
                ),
                "status": status,
                "score": int(a.score) if a.score is not None else None,
                "passed": bool(a.passed) if a.score is not None else bool(a.passed),
                "duration_seconds": duration_seconds,
                "href": (
                    f"/submodules/{ctx.get('submodule_id')}?module={ctx.get('module_id')}&quiz={a.quiz_id}"
                    if ctx.get("submodule_id")
                    else None
                ),
                "event_type": None,
                "ref_id": str(a.quiz_id) if a.quiz_id else None,
                "meta": None,
                "ip": None,
                "request_id": None,
                "module_id": ctx.get("module_id"),
                "module_title": ctx.get("module_title"),
                "submodule_id": ctx.get("submodule_id"),
                "submodule_title": ctx.get("submodule_title"),
                "asset_id": None,
                "asset_name": None,
            }
        )

    for se in sec_events:
        title, subtitle = _sec_event_display(se)
        items.append(
            {
                "id": f"security:{se.id}",
                "created_at": se.created_at.isoformat(),
                "kind": "security",
                "title": title,
                "subtitle": subtitle,
                "href": None,
                "event_type": se.event_type,
                "ref_id": None,
                "meta": se.meta,
                "ip": str(se.ip) if se.ip else None,
                "request_id": str(se.request_id) if se.request_id else None,
                "module_id": None,
                "module_title": None,
                "submodule_id": None,
                "submodule_title": None,
                "asset_id": None,
                "asset_name": None,
            }
        )

    for e in events:
        kind, title, subtitle, _code = _event_display(e)
        module_id = (
            subs_by_id.get(str(e.ref_id), {}).get("module_id")
            if e.ref_id and e.type.value == "submodule_opened"
            else subs_by_quiz_event.get(str(e.ref_id), {}).get("module_id")
        )
        module_title = (
            subs_by_id.get(str(e.ref_id), {}).get("module_title")
            if e.ref_id and e.type.value == "submodule_opened"
            else subs_by_quiz_event.get(str(e.ref_id), {}).get("module_title")
        )
        submodule_id = (
            subs_by_id.get(str(e.ref_id), {}).get("submodule_id")
            if e.ref_id and e.type.value == "submodule_opened"
            else subs_by_quiz_event.get(str(e.ref_id), {}).get("submodule_id")
        )
        submodule_title = (
            subs_by_id.get(str(e.ref_id), {}).get("submodule_title")
            if e.ref_id and e.type.value == "submodule_opened"
            else subs_by_quiz_event.get(str(e.ref_id), {}).get("submodule_title")
        )
        asset_id = assets_by_id.get(str(e.ref_id), {}).get("asset_id") if e.ref_id else None
        asset_name = assets_by_id.get(str(e.ref_id), {}).get("asset_name") if e.ref_id else None

        href = None
        if e.ref_id and e.type.value == "submodule_opened" and submodule_id and module_id:
            href = f"/submodules/{submodule_id}?module={module_id}"
        elif e.ref_id and e.type.value in ("quiz_started", "quiz_completed") and submodule_id and module_id:
            href = f"/submodules/{submodule_id}?module={module_id}&quiz={e.ref_id}"

        items.append(
            {
                "id": str(e.id),
                "created_at": e.created_at.isoformat(),
                "kind": kind,
                "title": title,
                "subtitle": subtitle or asset_name,
                "href": href,
                "event_type": e.type.value,
                "ref_id": str(e.ref_id) if e.ref_id else None,
                "meta": e.meta,
                "ip": None,
                "request_id": None,
                "module_id": module_id,
                "module_title": module_title,
                "submodule_id": submodule_id,
                "submodule_title": submodule_title,
                "asset_id": asset_id,
                "asset_name": asset_name,
            }
        )

    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return {"items": items[:take]}


@router.get("/recommendations")
def my_recommendations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    module_ids = recommend_next_modules(db, user_id=str(user.id), limit=3)
    return {"module_ids": module_ids}
