from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
import secrets
import string
from collections import defaultdict

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from passlib.context import CryptContext
from sqlalchemy import and_, bindparam, case, delete, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.core.security import require_roles
from app.core.security_audit_log import audit_log
from app.core.redis_client import get_redis
from app.db.session import get_db
from app.models.assignment import Assignment, AssignmentStatus, AssignmentType
from app.models.attempt import QuizAttempt
from app.models.attempt import QuizAttemptAnswer
from app.models.audit import LearningEvent, LearningEventType
from app.models.asset import ContentAsset
from app.models.module import Module, Submodule
from app.models.quiz import Question, Quiz
from app.models.security_audit import SecurityAuditEvent
from app.models.user import User, UserRole
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.quiz import QuestionType, QuizType
from app.models.skill import UserSkill
from app.schemas.analytics import ModuleAnalyticsResponse
from app.schemas.admin import (
    AssignmentCreateRequest,
    AssignmentCreateResponse,
    LinkAssetToSubmoduleRequest,
    LinkAssetToSubmoduleResponse,
    ModuleCreateRequest,
    ModuleCreateResponse,
    QuestionCreateRequest,
    QuestionCreateResponse,
    QuestionPublic,
    QuestionsListResponse,
    QuestionUpdateRequest,
    QuestionUpdateResponse,
    QuizCreateRequest,
    QuizCreateResponse,
    SubmoduleCreateRequest,
    SubmoduleCreateResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserForcePasswordChangeResponse,
    UserResetPasswordRequest,
    UserResetPasswordResponse,
    UserUpdateRequest,
    UserUpdateResponse,
)

from app.schemas.me import HistoryResponse

from app.services.learning import LearningService
from app.core.queue import fetch_job, get_queue
from app.services.module_import_jobs import import_module_zip_job
from app.services.content_migration_jobs import migrate_legacy_submodule_content_job
from app.services.quiz_regeneration_jobs import regenerate_module_quizzes_job, regenerate_submodule_quiz_job
from app.services.llm_handler import generate_quiz_questions_ai
from app.services.ollama import generate_quiz_questions_ollama
from app.services.hf_router import generate_quiz_questions_hf_router
from app.services.storage import ensure_bucket_exists, get_s3_client, presign_put, multipart_abort, multipart_complete, multipart_create, multipart_list_parts, multipart_presign_upload_part
from app.services.storage import s3_prefix_has_objects
from app.services.ollama import ollama_healthcheck
from app.services.openrouter_health import openrouter_healthcheck

router = APIRouter(prefix="/admin", tags=["admin"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _random_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(int(length)))


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _normalize_abcd_answer(raw: str) -> tuple[str, set[str]]:
    s = str(raw or "")
    letters = {ch.upper() for ch in re.findall(r"[A-Da-d]", s)}
    if not letters:
        return (s.strip(), set())
    canon = ",".join(sorted(letters))
    return (canon, letters)


def _normalize_correct_answer_for_type(*, qtype: str, raw: str) -> str:
    t = str(qtype or "").strip().lower()
    if t == "case":
        return str(raw or "")
    canon, letters = _normalize_abcd_answer(raw)
    if not letters:
        return str(raw or "")
    if t == "multi":
        return canon
    # single
    return sorted(letters)[0]


def _uuid(value: str, *, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid {field}") from e


def _delete_s3_prefix_best_effort(*, prefix: str) -> None:
    try:
        s3 = get_s3_client()
        token: str | None = None
        while True:
            kwargs: dict[str, object] = {
                "Bucket": settings.s3_bucket,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if token:
                kwargs["ContinuationToken"] = token
            resp = s3.list_objects_v2(**kwargs)
            contents = resp.get("Contents") or []
            if contents:
                keys = [{"Key": str(o.get("Key"))} for o in contents if o.get("Key")]
                if keys:
                    s3.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": keys, "Quiet": True})
            if not resp.get("IsTruncated"):
                break
            token = str(resp.get("NextContinuationToken") or "") or None
    except Exception:
        return


@router.get("/system/status")
def system_status(
    _: User = Depends(require_roles(UserRole.admin)),
):
    runtime: dict[str, str] = {}
    try:
        r = get_redis()
        raw = r.hgetall("runtime:llm") or {}
        for k, v in (raw or {}).items():
            kk = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
            vv = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
            runtime[kk] = vv
    except Exception:
        runtime = {}

    def _rt_bool(key: str) -> bool | None:
        v = (runtime.get(key) or "").strip().lower()
        if not v:
            return None
        return v in {"1", "true", "yes", "on"}

    def _rt_str(key: str) -> str:
        return str(runtime.get(key) or "").strip()

    eff_ollama_enabled = _rt_bool("ollama_enabled")
    if eff_ollama_enabled is None:
        eff_ollama_enabled = bool(getattr(settings, "ollama_enabled", False))
    eff_ollama_base_url = _rt_str("ollama_base_url") or str(getattr(settings, "ollama_base_url", ""))
    eff_ollama_model = _rt_str("ollama_model") or str(getattr(settings, "ollama_model", ""))

    eff_hf_enabled = _rt_bool("hf_router_enabled")
    if eff_hf_enabled is None:
        eff_hf_enabled = bool(getattr(settings, "hf_router_enabled", False))
    eff_hf_base_url = _rt_str("hf_router_base_url") or str(getattr(settings, "hf_router_base_url", ""))
    eff_hf_model = _rt_str("hf_router_model") or str(getattr(settings, "hf_router_model", ""))
    eff_hf_token = _rt_str("hf_router_token") or str(getattr(settings, "hf_router_token", "") or "")

    eff_or_enabled = _rt_bool("openrouter_enabled")
    if eff_or_enabled is None:
        eff_or_enabled = bool(getattr(settings, "openrouter_enabled", False))
    eff_or_base_url = _rt_str("openrouter_base_url") or str(getattr(settings, "openrouter_base_url", ""))
    eff_or_model = _rt_str("openrouter_model") or str(getattr(settings, "openrouter_model", ""))

    out: dict[str, object] = {
        "db": {"ok": False},
        "redis": {"ok": False},
        "rq": {"ok": False, "workers": 0, "queued": 0},
        "ollama": {"enabled": bool(eff_ollama_enabled), "ok": False, "reason": None},
        "s3": {"ok": False},
        "hf_router": {"enabled": bool(eff_hf_enabled), "ok": False, "reason": None},
        "openrouter": {"enabled": bool(eff_or_enabled), "ok": False, "reason": None},
    }

    try:
        db.execute(text("SELECT 1"))
        out["db"] = {"ok": True}
    except Exception as e:
        out["db"] = {"ok": False}

    try:
        r = get_redis()
        r.ping()
        out["redis"] = {"ok": True}
    except Exception:
        out["redis"] = {"ok": False}

    try:
        import redis as _redis
        from rq import Queue
        from rq.worker import Worker
        from rq.registry import DeferredJobRegistry, FailedJobRegistry, ScheduledJobRegistry, StartedJobRegistry

        conn = _redis.Redis.from_url(settings.redis_url)
        q = Queue(name="corelms", connection=conn)
        workers = Worker.all(connection=conn)
        started = StartedJobRegistry(queue=q, connection=conn)
        failed = FailedJobRegistry(queue=q, connection=conn)
        deferred = DeferredJobRegistry(queue=q, connection=conn)
        scheduled = ScheduledJobRegistry(queue=q, connection=conn)
        out["rq"] = {
            "ok": True,
            "workers": int(len(workers)),
            "queued": int(q.count),
            "started": int(getattr(started, "count", 0) or 0),
            "failed": int(getattr(failed, "count", 0) or 0),
            "deferred": int(getattr(deferred, "count", 0) or 0),
            "scheduled": int(getattr(scheduled, "count", 0) or 0),
        }
    except Exception:
        out["rq"] = {"ok": False, "workers": 0, "queued": 0, "started": 0, "failed": 0, "deferred": 0, "scheduled": 0}

    ok, reason = ollama_healthcheck(
        enabled=bool(eff_ollama_enabled),
        base_url=str(eff_ollama_base_url or "").strip() or None,
    )
    out["ollama"] = {
        "enabled": bool(eff_ollama_enabled),
        "ok": bool(ok),
        "reason": reason,
        "base_url": eff_ollama_base_url,
        "model": eff_ollama_model,
    }

    # S3
    try:
        ensure_bucket_exists()
        s3 = get_s3_client()
        s3.head_bucket(Bucket=settings.s3_bucket)
        out["s3"] = {"ok": True, "bucket": settings.s3_bucket, "endpoint": settings.s3_endpoint_url}
    except Exception:
        out["s3"] = {"ok": False, "bucket": settings.s3_bucket, "endpoint": settings.s3_endpoint_url}

    enabled = bool(eff_hf_enabled)
    token_present = bool((eff_hf_token or "").strip())
    out["hf_router"] = {
        "enabled": bool(enabled),
        "ok": bool(enabled and token_present),
        "reason": None if (enabled and token_present) else ("missing_token" if enabled else "disabled"),
        "base_url": eff_hf_base_url,
        "model": eff_hf_model,
    }

    ok_or, reason_or = openrouter_healthcheck(base_url=str(eff_or_base_url or "").strip() or None)
    out["openrouter"] = {
        "enabled": bool(eff_or_enabled),
        "ok": bool(ok_or),
        "reason": reason_or,
        "base_url": eff_or_base_url,
        "model": eff_or_model,
    }

    return out


class RuntimeLlmSettingsRequest(BaseModel):
    llm_provider_order: str | None = None

    ollama_enabled: bool | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None

    hf_router_enabled: bool | None = None
    hf_router_base_url: str | None = None
    hf_router_model: str | None = None
    hf_router_token: str | None = None

    openrouter_enabled: bool | None = None
    openrouter_base_url: str | None = None
    openrouter_model: str | None = None
    openrouter_api_key: str | None = None
    openrouter_http_referer: str | None = None
    openrouter_app_title: str | None = None


@router.get("/runtime/llm")
def get_runtime_llm_settings(
    _: User = Depends(require_roles(UserRole.admin)),
):
    try:
        r = get_redis()
        data = r.hgetall("runtime:llm") or {}
    except Exception:
        data = {}

    def _get(k: str) -> str:
        v = data.get(k)
        if v is None:
            return ""
        try:
            return v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            return str(v)

    token = _get("hf_router_token")
    masked = ""
    if token:
        masked = token[:4] + "…" + token[-4:]

    or_token = _get("openrouter_api_key")
    or_masked = ""
    if or_token:
        or_masked = or_token[:4] + "…" + or_token[-4:]

    enabled_raw = _get("hf_router_enabled")
    enabled = enabled_raw.lower() in {"1", "true", "yes", "on"}

    ollama_enabled_raw = _get("ollama_enabled")
    ollama_enabled = ollama_enabled_raw.lower() in {"1", "true", "yes", "on"}

    or_enabled_raw = _get("openrouter_enabled")
    or_enabled = or_enabled_raw.lower() in {"1", "true", "yes", "on"}

    def _eff_bool(rt_raw: str, env_val: bool) -> bool:
        s = (rt_raw or "").strip().lower()
        if not s:
            return bool(env_val)
        return s in {"1", "true", "yes", "on"}

    def _eff_str(rt_val: str, env_val: str | None) -> str:
        v = (rt_val or "").strip()
        if v:
            return v
        return str(env_val or "").strip()

    eff_token = _eff_str(_get("hf_router_token"), str(getattr(settings, "hf_router_token", "") or ""))
    eff_or_token = _eff_str(_get("openrouter_api_key"), str(getattr(settings, "openrouter_api_key", "") or ""))

    eff = {
        "llm_provider_order": _eff_str(_get("llm_provider_order"), str(getattr(settings, "llm_provider_order", ""))),
        "ollama_enabled": _eff_bool(_get("ollama_enabled"), bool(getattr(settings, "ollama_enabled", False))),
        "ollama_base_url": _eff_str(_get("ollama_base_url"), str(getattr(settings, "ollama_base_url", ""))),
        "ollama_model": _eff_str(_get("ollama_model"), str(getattr(settings, "ollama_model", ""))),
        "hf_router_enabled": _eff_bool(_get("hf_router_enabled"), bool(getattr(settings, "hf_router_enabled", False))),
        "hf_router_base_url": _eff_str(_get("hf_router_base_url"), str(getattr(settings, "hf_router_base_url", ""))),
        "hf_router_model": _eff_str(_get("hf_router_model"), str(getattr(settings, "hf_router_model", ""))),
        "hf_router_token_present": bool((eff_token or "").strip()),
        "openrouter_enabled": _eff_bool(_get("openrouter_enabled"), bool(getattr(settings, "openrouter_enabled", False))),
        "openrouter_base_url": _eff_str(_get("openrouter_base_url"), str(getattr(settings, "openrouter_base_url", ""))),
        "openrouter_model": _eff_str(_get("openrouter_model"), str(getattr(settings, "openrouter_model", ""))),
        "openrouter_api_key_present": bool((eff_or_token or "").strip()),
        "openrouter_http_referer": _eff_str(_get("openrouter_http_referer"), str(getattr(settings, "openrouter_http_referer", ""))),
        "openrouter_app_title": _eff_str(_get("openrouter_app_title"), str(getattr(settings, "openrouter_app_title", ""))),
    }

    return {
        "llm_provider_order": _get("llm_provider_order"),

        "ollama_enabled": bool(ollama_enabled),
        "ollama_base_url": _get("ollama_base_url"),
        "ollama_model": _get("ollama_model"),

        "hf_router_enabled": bool(enabled),
        "hf_router_base_url": _get("hf_router_base_url"),
        "hf_router_model": _get("hf_router_model"),
        "hf_router_token_masked": masked,

        "openrouter_enabled": bool(or_enabled),
        "openrouter_base_url": _get("openrouter_base_url"),
        "openrouter_model": _get("openrouter_model"),
        "openrouter_api_key_masked": or_masked,
        "openrouter_http_referer": _get("openrouter_http_referer"),
        "openrouter_app_title": _get("openrouter_app_title"),

        "effective": eff,
    }


@router.post("/runtime/llm")
def set_runtime_llm_settings(
    request: Request,
    body: RuntimeLlmSettingsRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    try:
        r = get_redis()
    except Exception:
        raise HTTPException(status_code=500, detail="redis unavailable")

    updates: dict[str, str] = {}
    if body.llm_provider_order is not None:
        updates["llm_provider_order"] = str(body.llm_provider_order or "").strip()

    if body.ollama_enabled is not None:
        updates["ollama_enabled"] = "1" if bool(body.ollama_enabled) else "0"
    if body.ollama_base_url is not None:
        updates["ollama_base_url"] = str(body.ollama_base_url or "").strip()
    if body.ollama_model is not None:
        updates["ollama_model"] = str(body.ollama_model or "").strip()

    if body.hf_router_enabled is not None:
        updates["hf_router_enabled"] = "1" if bool(body.hf_router_enabled) else "0"
    if body.hf_router_base_url is not None:
        updates["hf_router_base_url"] = str(body.hf_router_base_url or "").strip()
    if body.hf_router_model is not None:
        updates["hf_router_model"] = str(body.hf_router_model or "").strip()
    if body.hf_router_token is not None:
        # Allow clearing by sending empty string.
        updates["hf_router_token"] = str(body.hf_router_token or "").strip()

    if body.openrouter_enabled is not None:
        updates["openrouter_enabled"] = "1" if bool(body.openrouter_enabled) else "0"
    if body.openrouter_base_url is not None:
        updates["openrouter_base_url"] = str(body.openrouter_base_url or "").strip()
    if body.openrouter_model is not None:
        updates["openrouter_model"] = str(body.openrouter_model or "").strip()
    if body.openrouter_api_key is not None:
        updates["openrouter_api_key"] = str(body.openrouter_api_key or "").strip()
    if body.openrouter_http_referer is not None:
        updates["openrouter_http_referer"] = str(body.openrouter_http_referer or "").strip()
    if body.openrouter_app_title is not None:
        updates["openrouter_app_title"] = str(body.openrouter_app_title or "").strip()


    if updates:
        try:
            r.hset("runtime:llm", mapping=updates)
            r.expire("runtime:llm", 60 * 60 * 24 * 30)
        except Exception:
            raise HTTPException(status_code=500, detail="failed to save settings")

    try:
        audit_log(
            db=db,
            request=request,
            event_type="admin_set_runtime_llm_settings",
            actor_user_id=_.id,
            meta={"keys": list(updates.keys())},
        )
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    return {"ok": True}


@router.post("/maintenance/modules/purge-missing-storage")
def purge_modules_missing_storage(
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    dry_run: bool = Query(default=True),
    limit: int = Query(default=200),
    _: object = rate_limit(key_prefix="admin_purge_missing_storage", limit=10, window_seconds=60),
):
    take = max(1, min(int(limit or 200), 1000))

    mods = db.scalars(select(Module).order_by(Module.title).limit(take)).all()
    missing: list[Module] = []
    for m in mods:
        try:
            ok = s3_prefix_has_objects(prefix=f"modules/{m.id}/", bypass_cache=True)
        except Exception:
            ok = False
        if not ok:
            missing.append(m)

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "scanned": len(mods),
            "missing_count": len(missing),
            "items": [{"id": str(m.id), "title": str(m.title or "")} for m in missing[:50]],
        }

    deleted = 0
    for m in missing:
        mid = m.id
        try:
            sub_ids = list(db.scalars(select(Submodule.id).where(Submodule.module_id == mid)).all())
            quiz_ids = list(db.scalars(select(Submodule.quiz_id).where(Submodule.module_id == mid)).all())
            if m.final_quiz_id:
                quiz_ids.append(m.final_quiz_id)
            quiz_ids = [qid for qid in quiz_ids if qid is not None]
            quiz_ids = list({qid for qid in quiz_ids})

            asset_ids: set[uuid.UUID] = set()
            if sub_ids:
                rows = db.scalars(select(SubmoduleAssetMap.asset_id).where(SubmoduleAssetMap.submodule_id.in_(sub_ids))).all()
                for aid in rows:
                    if aid:
                        asset_ids.add(aid)

            prefix = f"modules/{str(mid)}/_module/"
            module_level_assets = db.scalars(select(ContentAsset.id).where(ContentAsset.object_key.like(prefix + "%"))).all()
            for aid in module_level_assets:
                if aid:
                    asset_ids.add(aid)

            # Break FK module.final_quiz_id -> quizzes
            m.final_quiz_id = None
            db.flush()

            if asset_ids:
                db.execute(delete(LearningEvent).where(LearningEvent.ref_id.in_(list(asset_ids))))

            if sub_ids:
                db.execute(delete(LearningEvent).where(LearningEvent.ref_id.in_(sub_ids)))
                db.execute(delete(SubmoduleAssetMap).where(SubmoduleAssetMap.submodule_id.in_(sub_ids)))
                db.execute(text("DELETE FROM submodules WHERE module_id = :mid"), {"mid": str(mid)})

            if quiz_ids:
                attempt_ids = list(db.scalars(select(QuizAttempt.id).where(QuizAttempt.quiz_id.in_(quiz_ids))).all())
                if attempt_ids:
                    db.execute(
                        text("DELETE FROM quiz_attempt_answers WHERE attempt_id IN :ids").bindparams(
                            bindparam("ids", expanding=True, value=attempt_ids)
                        )
                    )
                db.execute(delete(QuizAttempt).where(QuizAttempt.quiz_id.in_(quiz_ids)))
                db.execute(delete(Question).where(Question.quiz_id.in_(quiz_ids)))
                db.execute(delete(Quiz).where(Quiz.id.in_(quiz_ids)))

            if asset_ids:
                db.execute(delete(ContentAsset).where(ContentAsset.id.in_(list(asset_ids))))

            db.execute(text("DELETE FROM module_skill_map WHERE module_id = :mid"), {"mid": str(mid)})
            db.execute(text("DELETE FROM modules WHERE id = :mid"), {"mid": str(mid)})

            audit_log(
                db=db,
                request=request,
                event_type="admin_purge_module_missing_storage",
                actor_user_id=current.id,
                meta={"module_id": str(mid), "module_title": m.title},
            )

            deleted += 1
        except Exception:
            db.rollback()
            continue

    db.commit()
    return {
        "ok": True,
        "dry_run": False,
        "scanned": len(mods),
        "missing_count": len(missing),
        "deleted": deleted,
    }


@router.patch("/users/{user_id}", response_model=UserUpdateResponse)
def admin_update_user(
    request: Request,
    user_id: str,
    body: UserUpdateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_update_user", limit=60, window_seconds=60),
):
    uid = _uuid(user_id, field="user_id")
    u = db.scalar(select(User).where(User.id == uid))
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")

    name = body.name
    if name is not None:
        name = str(name).strip()
        if not name:
            raise HTTPException(status_code=400, detail="invalid name")
        existing = db.scalar(select(User).where(User.name == name, User.id != uid))
        if existing is not None:
            raise HTTPException(status_code=409, detail="user already exists")
        u.name = name

    if body.position is not None:
        pos = str(body.position).strip()
        u.position = pos or None

    role_raw = body.role
    if role_raw is not None:
        next_role = UserRole(str(role_raw))
        prev_role = getattr(u, "role", None)
        if prev_role == UserRole.admin and next_role != UserRole.admin:
            admins = int(db.scalar(select(func.count()).select_from(User).where(User.role == UserRole.admin)) or 0)
            if admins <= 1:
                raise HTTPException(status_code=400, detail="cannot demote last admin")
        u.role = next_role

    if body.must_change_password is not None:
        u.must_change_password = bool(body.must_change_password)
        if u.must_change_password:
            u.password_changed_at = None

    db.add(u)
    db.commit()

    audit_log(
        db=db,
        request=request,
        event_type="admin_update_user",
        actor_user_id=current.id,
        target_user_id=u.id,
        meta={
            "name": body.name,
            "position": body.position,
            "role": body.role,
            "must_change_password": body.must_change_password,
        },
    )
    db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/force-password-change", response_model=UserForcePasswordChangeResponse)
def admin_force_password_change(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_force_password_change", limit=60, window_seconds=60),
):
    uid = _uuid(user_id, field="user_id")
    u = db.scalar(select(User).where(User.id == uid))
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")

    u.must_change_password = True
    u.password_changed_at = None
    db.add(u)
    db.commit()

    audit_log(
        db=db,
        request=request,
        event_type="admin_force_password_change",
        actor_user_id=current.id,
        target_user_id=u.id,
    )
    db.commit()
    return {"ok": True}


@router.get("/modules/{module_id}/submodules/quality")
def module_submodules_quality(
    module_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    mid = _uuid(module_id, field="module_id")
    m = db.scalar(select(Module).where(Module.id == mid))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    needs_regen_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("needs_regen:%"))
    needs_ai_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("needs_ai:%"))
    fallback_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("%fallback%"))
    ai_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("regen:%"))
    heur_cond = (Question.concept_tag.is_not(None)) & (
        Question.concept_tag.like("heur:%") | Question.concept_tag.like("needs_ai:heur:%")
    )

    rows = (
        db.execute(
            select(
                Submodule.id.label("submodule_id"),
                Submodule.order.label("order"),
                Submodule.title.label("title"),
                Submodule.quiz_id.label("quiz_id"),
                func.count(Question.id).label("total"),
                func.sum(case((needs_regen_cond | needs_ai_cond, 1), else_=0)).label("needs_regen"),
                func.sum(case((fallback_cond, 1), else_=0)).label("fallback"),
                func.sum(case((ai_cond, 1), else_=0)).label("ai"),
                func.sum(case((heur_cond, 1), else_=0)).label("heur"),
            )
            .select_from(Submodule)
            .join(Question, Question.quiz_id == Submodule.quiz_id, isouter=True)
            .where(Submodule.module_id == mid)
            .group_by(Submodule.id)
            .order_by(Submodule.order)
        )
        .all()
    )

    items: list[dict[str, object]] = []
    for r in rows:
        total = int(getattr(r, "total", 0) or 0)
        needs = int(getattr(r, "needs_regen", 0) or 0)
        items.append(
            {
                "submodule_id": str(r.submodule_id),
                "submodule_title": str(getattr(r, "title", "") or ""),
                "total": total,
                "needs_regen": needs,
                "fallback": int(getattr(r, "fallback", 0) or 0),
                "ai": int(getattr(r, "ai", 0) or 0),
                "heur": int(getattr(r, "heur", 0) or 0),
                "ok": bool(needs <= 0 and int(getattr(r, "fallback", 0) or 0) <= 0 and int(getattr(r, "heur", 0) or 0) <= 0 and total >= 5),
            }
        )

    return {"ok": True, "module_id": str(m.id), "items": items}

class LlmProbeRequest(BaseModel):
    title: str = "Проба"
    text: str = ""
    n_questions: int = 3
    providers: list[str] | None = None


@router.post("/llm/probe")
def llm_probe(
    body: LlmProbeRequest,
    _: User = Depends(require_roles(UserRole.admin)),
):
    title = str(body.title or "Проба")
    text = str(body.text or "")
    n = max(1, min(int(body.n_questions or 3), 10))
    providers = [p.strip().lower() for p in (body.providers or ["ollama", "hf_router", "auto"]) if str(p).strip()]

    # Snapshot runtime overrides
    runtime: dict[str, str] = {}
    try:
        r = get_redis()
        raw = r.hgetall("runtime:llm") or {}
        for k, v in (raw or {}).items():
            kk = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
            vv = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
            runtime[kk] = vv
    except Exception:
        runtime = {}

    out: dict[str, object] = {
        "settings": {
            "ollama_enabled": bool(settings.ollama_enabled),
            "ollama_base_url": settings.ollama_base_url,
            "ollama_model": settings.ollama_model,
            "hf_router_enabled": bool(settings.hf_router_enabled),
            "hf_router_base_url": settings.hf_router_base_url,
            "hf_router_model": settings.hf_router_model,
            "llm_provider_order": settings.llm_provider_order,
        },
        "runtime": {
            "llm_provider_order": runtime.get("llm_provider_order") or "",
            "hf_router_enabled": runtime.get("hf_router_enabled") or "",
            "hf_router_token_present": bool((runtime.get("hf_router_token") or "").strip()),
        },
        "results": {},
    }

    if "ollama" in providers:
        dbg: dict[str, object] = {}
        qs = generate_quiz_questions_ollama(title=title, text=text, n_questions=n, debug_out=dbg)
        out["results"]["ollama"] = {
            "ok": bool(qs),
            "count": int(len(qs or [])),
            "debug": dbg,
            "sample": [q.model_dump() if hasattr(q, "model_dump") else dict(q) for q in (qs or [])[:2]],
        }

    if "hf_router" in providers:
        dbg2: dict[str, object] = {}
        qs2 = generate_quiz_questions_hf_router(title=title, text=text, n_questions=n, debug_out=dbg2)
        out["results"]["hf_router"] = {
            "ok": bool(qs2),
            "count": int(len(qs2 or [])),
            "debug": dbg2,
            "sample": [q.model_dump() if hasattr(q, "model_dump") else dict(q) for q in (qs2 or [])[:2]],
        }

    if "auto" in providers:
        dbg3: dict[str, object] = {}
        qs3 = generate_quiz_questions_ai(title=title, text=text, n_questions=n, debug_out=dbg3)
        out["results"]["auto"] = {
            "ok": bool(qs3),
            "count": int(len(qs3 or [])),
            "debug": dbg3,
            "sample": [getattr(q, "model_dump", lambda: dict(q))() if q is not None else {} for q in (qs3 or [])[:2]],
        }

    return out


@router.post("/modules/import-zip")
async def import_module_zip(
    request: Request,
    title: str | None = None,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_import_module_zip", limit=15, window_seconds=60),
):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="only .zip is supported")

    t = (title or "").strip()
    inferred_title: str | None = None
    try:
        fn = str(file.filename or "").strip()
        if fn:
            inferred_title = re.sub(r"\.zip$", "", fn, flags=re.IGNORECASE).strip() or None
    except Exception:
        inferred_title = None

    effective_title = t or inferred_title
    if effective_title:
        exists = (
            db.scalar(
                select(func.count()).select_from(Module).where(func.lower(Module.title) == func.lower(effective_title))
            )
            or 0
        )
        if int(exists) > 0:
            raise HTTPException(status_code=409, detail="module title already exists")

    ensure_bucket_exists()
    s3 = get_s3_client()

    object_key = f"uploads/admin/{uuid.uuid4()}.zip"
    try:
        try:
            file.file.seek(0)
        except Exception:
            pass

        s3.put_object(Bucket=settings.s3_bucket, Key=object_key, Body=file.file, ContentType="application/zip")
    except Exception as e:
        raise HTTPException(status_code=500, detail="failed to upload zip") from e

    # Product rule: module should appear immediately in list as hidden while import/regen runs.
    stub_module = None
    try:
        stub_title = str(effective_title or "").strip() or str(file.filename or "").strip() or "Модуль"
        if stub_title.lower().endswith(".zip"):
            stub_title = stub_title[:-4]
        stub_title = stub_title.strip() or "Модуль"

        final_quiz = Quiz(type=QuizType.final, pass_threshold=70, time_limit=None, attempts_limit=3)
        db.add(final_quiz)
        db.flush()
        stub_module = Module(
            title=stub_title,
            description=f"Материалы модуля «{stub_title}».",
            difficulty=1,
            category="Обучение",
            is_active=False,
            final_quiz_id=final_quiz.id,
        )
        db.add(stub_module)
        db.flush()
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        stub_module = None

    try:
        q = get_queue("corelms")
        job = q.enqueue(
            import_module_zip_job,
            s3_object_key=object_key,
            title=(effective_title or None),
            source_filename=(file.filename or None),
            actor_user_id=str(current.id),
            module_id=str(stub_module.id) if stub_module is not None else None,
            job_timeout=60 * 60 * 3,
            result_ttl=60 * 60 * 24,
            failure_ttl=60 * 60 * 24,
        )
    except Exception as e:
        try:
            s3.delete_object(Bucket=settings.s3_bucket, Key=object_key)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="failed to enqueue import job") from e

    try:
        jm = dict(job.meta or {})
        jm["job_kind"] = "import"
        if stub_module is not None:
            jm["module_id"] = str(stub_module.id)
            jm["module_title"] = str(stub_module.title)
        fingerprint = ""
        try:
            ensure_bucket_exists()
            s3 = get_s3_client()
            head = s3.head_object(Bucket=settings.s3_bucket, Key=object_key)
            etag = str(head.get("ETag") or "").strip().strip('"')
            size = str(head.get("ContentLength") or "").strip()
            if etag and size:
                fingerprint = f"{etag}:{size}"
        except Exception:
            fingerprint = ""
        if fingerprint:
            jm["import_fingerprint"] = fingerprint
        try:
            if meta.get("object_key"):
                jm["import_object_key"] = str(meta.get("object_key") or "")
        except Exception:
            pass
        job.meta = jm
        job.save_meta()
    except Exception:
        pass

    # Best-effort: establish dedupe keys for the retried job.
    if fingerprint:
        try:
            r = get_redis()
            r.set(f"admin:import_enqueued_by_fingerprint:{fingerprint}", str(job.id))
            r.expire(f"admin:import_enqueued_by_fingerprint:{fingerprint}", 60 * 60 * 6)
            if stub_module is not None:
                r.set(f"admin:import_fingerprint_by_module_id:{str(stub_module.id)}", fingerprint)
                r.expire(f"admin:import_fingerprint_by_module_id:{str(stub_module.id)}", 60 * 60 * 24 * 30)
        except Exception:
            pass

    try:
        r = get_redis()
        meta = {
            "job_id": job.id,
            "object_key": object_key,
            "title": (effective_title or "").strip(),
            "created_at": datetime.utcnow().isoformat(),
            "actor_user_id": str(current.id),
            "source_filename": str(file.filename or "")[:200],
            "source": "legacy_multipart",
            "module_id": str(stub_module.id) if stub_module is not None else "",
            "module_title": str(stub_module.title) if stub_module is not None else "",
        }
        r.lpush("admin:import_jobs", json.dumps(meta, ensure_ascii=False))
        r.ltrim("admin:import_jobs", 0, 49)
        r.expire("admin:import_jobs", 60 * 60 * 24 * 30)
    except Exception:
        pass

    audit_log(
        db=db,
        request=request,
        event_type="admin_import_module_zip",
        actor_user_id=current.id,
        meta={"job_id": job.id, "object_key": object_key, "title": effective_title},
    )

    return {
        "ok": True,
        "job_id": job.id,
        "object_key": object_key,
        "module_id": str(stub_module.id) if stub_module is not None else None,
    }


class AdminAbortUploadRequest(BaseModel):
    object_key: str
    filename: str | None = None


@router.post("/modules/abort-import-zip")
def abort_import_zip(
    request: Request,
    body: AdminAbortUploadRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    __: object = rate_limit(key_prefix="admin_abort_import_zip", limit=30, window_seconds=60),
):
    object_key = str(body.object_key or "").strip()
    if not object_key:
        raise HTTPException(status_code=400, detail="missing object_key")

    fingerprint = ""
    try:
        ensure_bucket_exists()
        s3 = get_s3_client()
        head = s3.head_object(Bucket=settings.s3_bucket, Key=object_key)
        etag = str(head.get("ETag") or "").strip().strip('"')
        size = str(head.get("ContentLength") or "").strip()
        if etag and size:
            fingerprint = f"{etag}:{size}"
    except Exception:
        fingerprint = ""

    # Best-effort delete the uploaded (or partially uploaded) object.
    try:
        ensure_bucket_exists()
        s3 = get_s3_client()
        s3.delete_object(Bucket=settings.s3_bucket, Key=object_key)
    except Exception:
        pass

    # Best-effort clear filename->object_key mapping to avoid future 'reused' pointing to an aborted upload.
    fn = str(body.filename or "").strip()
    if fn:
        norm_fn = re.sub(r"\s+", " ", fn).strip().lower()
        try:
            r = get_redis()
            k = f"admin:import_zip_by_filename:{norm_fn}"
            existing = str(r.get(k) or "").strip()
            if existing == object_key:
                r.delete(k)
        except Exception:
            pass

    # Best-effort release fingerprint dedupe key (if any).
    if fingerprint:
        try:
            r = get_redis()
            r.delete(f"admin:import_enqueued_by_fingerprint:{fingerprint}")
        except Exception:
            pass

    audit_log(
        db=db,
        request=request,
        event_type="admin_abort_import_module_zip",
        actor_user_id=None,
        meta={"object_key": object_key, "filename": fn or None},
    )
    db.commit()

    return {"ok": True}


class AdminBucketCorsRule(BaseModel):
    allowed_origins: list[str]
    allowed_methods: list[str]
    allowed_headers: list[str] | None = None
    expose_headers: list[str] | None = None
    max_age_seconds: int | None = None


class AdminBucketCorsRequest(BaseModel):
    rules: list[AdminBucketCorsRule]


@router.get("/storage/bucket-cors")
def get_bucket_cors(
    _: User = Depends(require_roles(UserRole.admin)),
):
    ensure_bucket_exists()
    s3 = get_s3_client()
    try:
        cfg = s3.get_bucket_cors(Bucket=settings.s3_bucket) or {}
    except Exception as e:
        # Some providers return NoSuchCORSConfiguration
        return {"ok": True, "bucket": settings.s3_bucket, "rules": [], "detail": str(e)[:300]}

    rules = cfg.get("CORSRules") or []
    out: list[dict[str, object]] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "allowed_origins": list(r.get("AllowedOrigins") or []),
                "allowed_methods": list(r.get("AllowedMethods") or []),
                "allowed_headers": list(r.get("AllowedHeaders") or []),
                "expose_headers": list(r.get("ExposeHeaders") or []),
                "max_age_seconds": r.get("MaxAgeSeconds"),
            }
        )
    return {"ok": True, "bucket": settings.s3_bucket, "rules": out}


@router.post("/storage/bucket-cors")
def set_bucket_cors(
    request: Request,
    body: AdminBucketCorsRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_set_bucket_cors", limit=10, window_seconds=60),
):
    ensure_bucket_exists()
    s3 = get_s3_client()

    cors_rules: list[dict[str, object]] = []
    for r in body.rules or []:
        origins = [str(x or "").strip() for x in (r.allowed_origins or []) if str(x or "").strip()]
        methods = [str(x or "").strip().upper() for x in (r.allowed_methods or []) if str(x or "").strip()]
        if not origins or not methods:
            continue
        rule: dict[str, object] = {
            "AllowedOrigins": origins,
            "AllowedMethods": methods,
            "AllowedHeaders": ["*"] if not r.allowed_headers else [str(x) for x in (r.allowed_headers or [])],
        }
        if r.expose_headers:
            rule["ExposeHeaders"] = [str(x) for x in (r.expose_headers or [])]
        if r.max_age_seconds is not None:
            rule["MaxAgeSeconds"] = int(r.max_age_seconds)
        cors_rules.append(rule)

    if not cors_rules:
        raise HTTPException(status_code=400, detail="no valid cors rules")

    try:
        s3.put_bucket_cors(Bucket=settings.s3_bucket, CORSConfiguration={"CORSRules": cors_rules})
    except Exception as e:
        raise HTTPException(status_code=500, detail="failed to set bucket cors") from e

    audit_log(
        db=db,
        request=request,
        event_type="admin_set_bucket_cors",
        actor_user_id=current.id,
        meta={"bucket": settings.s3_bucket, "rules": cors_rules},
    )
    db.commit()

    return {"ok": True, "bucket": settings.s3_bucket, "rules": cors_rules}


class AdminPresignImportZipRequest(BaseModel):
    filename: str
    content_type: str | None = None
    size_bytes: int | None = None
    last_modified_ms: int | None = None


class AdminMultipartCreateRequest(BaseModel):
    filename: str
    content_type: str | None = None
    size_bytes: int | None = None
    last_modified_ms: int | None = None


class AdminMultipartCreateResponse(BaseModel):
    ok: bool = True
    object_key: str
    upload_id: str
    reused: bool = False


class AdminMultipartPresignPartRequest(BaseModel):
    object_key: str
    upload_id: str
    part_number: int


class AdminMultipartPresignPartResponse(BaseModel):
    ok: bool = True
    upload_url: str


class AdminMultipartListPartsRequest(BaseModel):
    object_key: str
    upload_id: str


class AdminMultipartListPartsResponse(BaseModel):
    ok: bool = True
    parts: list[dict[str, object]]


class AdminMultipartCompleteRequest(BaseModel):
    object_key: str
    upload_id: str
    parts: list[dict[str, object]]


class AdminMultipartAbortRequest(BaseModel):
    object_key: str
    upload_id: str


class AdminPresignImportZipResponse(BaseModel):
    ok: bool = True
    object_key: str
    upload_url: str | None = None
    reused: bool = False


@router.post("/modules/presign-import-zip", response_model=AdminPresignImportZipResponse)
def presign_import_zip(
    request: Request,
    body: AdminPresignImportZipRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    __: object = rate_limit(key_prefix="admin_presign_import_zip", limit=60, window_seconds=60),
):
    fn = str(body.filename or "").strip()
    if not fn.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="only .zip is supported")

    # Dedupe: if a ZIP with the same fingerprint was already uploaded, reuse it.
    # This allows resume without re-upload (upload to storage first, then enqueue processing).
    norm_fn = re.sub(r"\s+", " ", fn).strip().lower()
    sz = None
    lm = None
    try:
        if body.size_bytes is not None:
            sz = int(body.size_bytes)
    except Exception:
        sz = None
    try:
        if body.last_modified_ms is not None:
            lm = int(body.last_modified_ms)
    except Exception:
        lm = None

    # If client does not provide size/mtime, fallback to legacy behavior (filename-only).
    fp = f"{norm_fn}:{sz}:{lm}" if (sz is not None and lm is not None) else norm_fn
    try:
        r = get_redis()
        existing_key = str(r.get(f"admin:import_zip_by_fingerprint:{fp}") or "").strip()
    except Exception:
        existing_key = ""

    if existing_key:
        try:
            ensure_bucket_exists()
            s3 = get_s3_client()
            s3.head_object(Bucket=settings.s3_bucket, Key=existing_key)
            return {"ok": True, "object_key": existing_key, "upload_url": None, "reused": True}
        except Exception:
            # If object is missing, fall through to generating a new presign.
            pass

    # Keep the uploaded zip in the same prefix used by legacy flow.
    safe = re.sub(r"[^a-zA-Z0-9\-_.]+", "-", norm_fn).strip("-._")
    safe = re.sub(r"-+", "-", safe)[:80] or "module"
    object_key = f"uploads/admin/{safe}__{uuid.uuid4()}.zip"
    try:
        # Do not bind the presigned URL to Content-Type.
        # Browsers may send a slightly different content-type (or none), which would cause SignatureDoesNotMatch.
        url = presign_put(object_key=object_key, content_type=None)
    except Exception as e:
        raise HTTPException(status_code=500, detail="failed to presign upload url") from e

    try:
        r = get_redis()
        r.set(f"admin:import_zip_by_fingerprint:{fp}", object_key)
        r.expire(f"admin:import_zip_by_fingerprint:{fp}", 60 * 60 * 24 * 30)
    except Exception:
        pass

    audit_log(
        db=db,
        request=request,
        event_type="admin_presign_import_module_zip",
        actor_user_id=None,
        meta={"object_key": object_key, "filename": fn},
    )
    db.commit()

    return {"ok": True, "object_key": object_key, "upload_url": url, "reused": False}


@router.post("/modules/multipart-import-create", response_model=AdminMultipartCreateResponse)
def multipart_import_create(
    request: Request,
    body: AdminMultipartCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    __: object = rate_limit(key_prefix="admin_multipart_import_create", limit=30, window_seconds=60),
):
    fn = str(body.filename or "").strip()
    if not fn.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="only .zip is supported")

    norm_fn = re.sub(r"\s+", " ", fn).strip().lower()
    sz = None
    lm = None
    try:
        if body.size_bytes is not None:
            sz = int(body.size_bytes)
    except Exception:
        sz = None
    try:
        if body.last_modified_ms is not None:
            lm = int(body.last_modified_ms)
    except Exception:
        lm = None

    fp = f"{norm_fn}:{sz}:{lm}" if (sz is not None and lm is not None) else norm_fn
    sess_key = f"admin:import_multipart_by_fingerprint:{fp}"
    try:
        r = get_redis()
        raw = str(r.get(sess_key) or "").strip()
    except Exception:
        raw = ""

    if raw:
        try:
            obj = json.loads(raw)
            object_key = str((obj or {}).get("object_key") or "").strip()
            upload_id = str((obj or {}).get("upload_id") or "").strip()
            if object_key and upload_id:
                return {"ok": True, "object_key": object_key, "upload_id": upload_id, "reused": True}
        except Exception:
            pass

    safe = re.sub(r"[^a-zA-Z0-9\-_.]+", "-", norm_fn).strip("-._")
    safe = re.sub(r"-+", "-", safe)[:80] or "module"
    object_key = f"uploads/admin/{safe}__{uuid.uuid4()}.zip"
    upload_id = multipart_create(object_key=object_key, content_type=str(body.content_type or "").strip() or None)
    if not upload_id:
        raise HTTPException(status_code=500, detail="failed to create multipart upload")

    try:
        r = get_redis()
        r.set(sess_key, json.dumps({"object_key": object_key, "upload_id": upload_id}, ensure_ascii=False))
        r.expire(sess_key, 60 * 60 * 24 * 30)
    except Exception:
        pass

    audit_log(
        db=db,
        request=request,
        event_type="admin_multipart_import_create",
        actor_user_id=None,
        meta={"object_key": object_key, "filename": fn},
    )
    db.commit()

    return {"ok": True, "object_key": object_key, "upload_id": upload_id, "reused": False}


@router.post("/modules/multipart-import-presign-part", response_model=AdminMultipartPresignPartResponse)
def multipart_import_presign_part(
    request: Request,
    body: AdminMultipartPresignPartRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_multipart_import_presign_part", limit=240, window_seconds=60),
):
    object_key = str(body.object_key or "").strip()
    upload_id = str(body.upload_id or "").strip()
    pn = int(body.part_number or 0)
    if not object_key or not upload_id or pn <= 0:
        raise HTTPException(status_code=400, detail="invalid multipart params")

    url = multipart_presign_upload_part(object_key=object_key, upload_id=upload_id, part_number=pn)
    audit_log(
        db=db,
        request=request,
        event_type="admin_multipart_import_presign_part",
        actor_user_id=current.id,
        meta={"object_key": object_key, "part_number": pn},
    )
    db.commit()
    return {"ok": True, "upload_url": url}


@router.post("/modules/multipart-import-list-parts", response_model=AdminMultipartListPartsResponse)
def multipart_import_list_parts(
    body: AdminMultipartListPartsRequest,
    _: User = Depends(require_roles(UserRole.admin)),
    __: object = rate_limit(key_prefix="admin_multipart_import_list_parts", limit=120, window_seconds=60),
):
    object_key = str(body.object_key or "").strip()
    upload_id = str(body.upload_id or "").strip()
    if not object_key or not upload_id:
        raise HTTPException(status_code=400, detail="invalid multipart params")
    parts = multipart_list_parts(object_key=object_key, upload_id=upload_id)
    return {"ok": True, "parts": parts}


@router.post("/modules/multipart-import-complete")
def multipart_import_complete(
    request: Request,
    body: AdminMultipartCompleteRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_multipart_import_complete", limit=30, window_seconds=60),
):
    object_key = str(body.object_key or "").strip()
    upload_id = str(body.upload_id or "").strip()
    if not object_key or not upload_id:
        raise HTTPException(status_code=400, detail="invalid multipart params")
    multipart_complete(object_key=object_key, upload_id=upload_id, parts=list(body.parts or []))
    audit_log(
        db=db,
        request=request,
        event_type="admin_multipart_import_complete",
        actor_user_id=current.id,
        meta={"object_key": object_key},
    )
    db.commit()
    return {"ok": True, "object_key": object_key}


@router.post("/modules/multipart-import-abort")
def multipart_import_abort(
    request: Request,
    body: AdminMultipartAbortRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_multipart_import_abort", limit=30, window_seconds=60),
):
    object_key = str(body.object_key or "").strip()
    upload_id = str(body.upload_id or "").strip()
    if not object_key or not upload_id:
        raise HTTPException(status_code=400, detail="invalid multipart params")
    try:
        multipart_abort(object_key=object_key, upload_id=upload_id)
    except Exception:
        pass
    audit_log(
        db=db,
        request=request,
        event_type="admin_multipart_import_abort",
        actor_user_id=current.id,
        meta={"object_key": object_key},
    )
    db.commit()
    return {"ok": True}


class AdminEnqueueImportZipRequest(BaseModel):
    object_key: str
    title: str | None = None
    source_filename: str | None = None


@router.post("/modules/enqueue-import-zip")
def enqueue_import_zip(
    request: Request,
    body: AdminEnqueueImportZipRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_enqueue_import_zip", limit=30, window_seconds=60),
):
    object_key = str(body.object_key or "").strip()
    if not object_key:
        raise HTTPException(status_code=400, detail="missing object_key")

    fingerprint = ""
    try:
        ensure_bucket_exists()
        s3 = get_s3_client()
        head = s3.head_object(Bucket=settings.s3_bucket, Key=object_key)
        etag = str(head.get("ETag") or "").strip().strip('"')
        size = str(head.get("ContentLength") or "").strip()
        if etag and size:
            fingerprint = f"{etag}:{size}"
    except Exception:
        fingerprint = ""

    # Dedupe: avoid enqueuing the same uploaded ZIP multiple times.
    # Allows UI to safely retry enqueue after refresh without duplicating work.
    try:
        r = get_redis()
        lock_key = f"admin:import_enqueued_by_object_key:{object_key}"
        existing_job_id = str(r.get(lock_key) or "").strip()
        if existing_job_id:
            raise HTTPException(status_code=409, detail=f"zip already enqueued: {existing_job_id}")
    except HTTPException:
        raise
    except Exception:
        pass

    try:
        if fingerprint:
            r = get_redis()
            fp_key = f"admin:import_enqueued_by_fingerprint:{fingerprint}"
            existing_fp_job_id = str(r.get(fp_key) or "").strip()
            if existing_fp_job_id:
                raise HTTPException(status_code=409, detail=f"zip already enqueued (fingerprint): {existing_fp_job_id}")
    except HTTPException:
        raise
    except Exception:
        pass

    title = (str(body.title or "").strip() or None)
    norm_title = None
    if title:
        norm_title = re.sub(r"\s+", " ", title).strip().lower()
    if title:
        exists = (
            db.scalar(select(func.count()).select_from(Module).where(func.lower(Module.title) == func.lower(title))) or 0
        )
        if int(exists) > 0:
            raise HTTPException(status_code=409, detail="module title already exists")

    # Product rule: module should appear immediately in list as hidden while import/regen runs.
    # Create a stub module now, then let the worker populate it.
    stub_module = None
    try:
        stub_title = title or (str(body.source_filename or "").strip() or "Модуль")
        # Trim .zip from filename for nicer stub title.
        if stub_title.lower().endswith(".zip"):
            stub_title = stub_title[:-4]
        stub_title = stub_title.strip() or "Модуль"

        final_quiz = Quiz(type=QuizType.final, pass_threshold=70, time_limit=None, attempts_limit=3)
        db.add(final_quiz)
        db.flush()
        stub_module = Module(
            title=stub_title,
            description=f"Материалы модуля «{stub_title}».",
            difficulty=1,
            category="Обучение",
            is_active=False,
            final_quiz_id=final_quiz.id,
        )
        db.add(stub_module)
        db.flush()
    except Exception:
        stub_module = None

    # Dedupe: avoid enqueuing multiple jobs for the same target module title.
    # This prevents queue spam when the UI retries / user clicks repeatedly.
    title_lock_key = None
    try:
        if norm_title:
            r = get_redis()
            title_lock_key = f"admin:import_enqueued_by_title:{norm_title}"
            existing_title_job_id = str(r.get(title_lock_key) or "").strip()
            if existing_title_job_id:
                raise HTTPException(status_code=409, detail=f"module title already enqueued: {existing_title_job_id}")
    except HTTPException:
        raise
    except Exception:
        title_lock_key = None

    if not fingerprint:
        raise HTTPException(status_code=404, detail="source zip not found in s3")

    try:
        q = get_queue("corelms")
        job = q.enqueue(
            import_module_zip_job,
            s3_object_key=object_key,
            title=title,
            source_filename=(str(body.source_filename or "").strip() or None),
            actor_user_id=str(current.id),
            module_id=str(stub_module.id) if stub_module is not None else None,
            job_timeout=60 * 60 * 3,
            result_ttl=60 * 60 * 24,
            failure_ttl=60 * 60 * 24,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="failed to enqueue import job") from e

    # Store normalized title in job.meta so the worker can release title locks on end.
    try:
        if norm_title or fingerprint:
            jm = dict(job.meta or {})
            if norm_title:
                jm["import_title_norm"] = norm_title
            jm["import_object_key"] = object_key
            if fingerprint:
                jm["import_fingerprint"] = fingerprint
            if stub_module is not None:
                jm["job_kind"] = "import"
                jm["module_id"] = str(stub_module.id)
                jm["module_title"] = str(stub_module.title)
            job.meta = jm
            job.save_meta()
    except Exception:
        pass

    # Commit stub module so it becomes visible immediately to admin list endpoints.
    try:
        db.commit()
    except Exception:
        db.rollback()

    try:
        r = get_redis()
        r.set(lock_key, str(job.id))
        r.expire(lock_key, 60 * 60 * 6)
        if title_lock_key:
            r.set(title_lock_key, str(job.id))
            r.expire(title_lock_key, 60 * 60 * 24 * 30)
        if fingerprint:
            fp_key = f"admin:import_enqueued_by_fingerprint:{fingerprint}"
            r.set(fp_key, str(job.id))
            r.expire(fp_key, 60 * 60 * 6)
            # Reverse mapping: allows immediate unlock when module is deleted.
            if stub_module is not None:
                r.set(f"admin:import_fingerprint_by_module_id:{str(stub_module.id)}", fingerprint)
                r.expire(f"admin:import_fingerprint_by_module_id:{str(stub_module.id)}", 60 * 60 * 24 * 30)
    except Exception:
        pass

    try:
        r = get_redis()
        meta = {
            "job_id": job.id,
            "object_key": object_key,
            "title": title or "",
            "created_at": datetime.utcnow().isoformat(),
            "actor_user_id": str(current.id),
            "source_filename": str(body.source_filename or "")[:200],
            "source": "direct_s3",
            "module_id": str(stub_module.id) if stub_module is not None else "",
            "module_title": str(stub_module.title) if stub_module is not None else "",
        }
        r.lpush("admin:import_jobs", json.dumps(meta, ensure_ascii=False))
        r.ltrim("admin:import_jobs", 0, 49)
        r.expire("admin:import_jobs", 60 * 60 * 24 * 30)
    except Exception:
        pass

    audit_log(
        db=db,
        request=request,
        event_type="admin_enqueue_import_module_zip",
        actor_user_id=current.id,
        meta={"job_id": job.id, "object_key": object_key, "title": title or ""},
    )
    db.commit()

    return {
        "ok": True,
        "job_id": job.id,
        "object_key": object_key,
        "module_id": str(stub_module.id) if stub_module is not None else None,
    }


@router.get("/import-jobs")
def list_import_jobs(
    limit: int = 20,
    include_terminal: bool = False,
    _: User = Depends(require_roles(UserRole.admin)),
):
    take = max(1, min(int(limit or 20), 50))
    include_terminal = bool(include_terminal)
    try:
        r = get_redis()
        raw = r.lrange("admin:import_jobs", 0, 200)
        raw_hist = r.lrange("admin:import_jobs_history", 0, 200) if include_terminal else []
    except Exception:
        raw = []
        raw_hist = []

    def _enrich(obj: dict) -> tuple[dict, bool]:
        job_id = str(obj.get("job_id") or "").strip()
        job = fetch_job(job_id) if job_id else None
        if job is None:
            obj["status"] = "missing"
            obj["stage"] = "missing"
            obj["error_code"] = obj.get("error_code") or "JOB_NOT_FOUND"
            obj["error_hint"] = obj.get("error_hint") or "Задача уже удалена из очереди (TTL) или была очищена. Обновите историю."
            obj["error_message"] = obj.get("error_message") or "job not found"
            obj["cancel_requested"] = bool(obj.get("cancel_requested"))
            obj["error"] = obj.get("error") or "job not found"
            return obj, True

        st = str(job.get_status(refresh=True) or "").strip().lower()
        meta = dict(job.meta or {})
        stage = str(meta.get("stage") or "").strip().lower()

        obj["status"] = st
        obj["stage"] = meta.get("stage")
        obj["stage_at"] = meta.get("stage_at")
        obj["detail"] = meta.get("detail")
        obj["error_code"] = meta.get("error_code")
        obj["error_hint"] = meta.get("error_hint")
        obj["error_message"] = meta.get("error_message")
        obj["cancel_requested"] = bool(meta.get("cancel_requested"))

        terminal = st in {"finished", "failed", "canceled"} or stage == "canceled"

        try:
            if terminal and st == "finished":
                res = job.result
                if isinstance(res, dict):
                    if not obj.get("module_id") and res.get("module_id"):
                        obj["module_id"] = str(res.get("module_id"))
                    rep = res.get("report") if isinstance(res.get("report"), dict) else None
                    if rep and not obj.get("module_title") and rep.get("module_title"):
                        obj["module_title"] = str(rep.get("module_title"))
        except Exception:
            pass

        try:
            if terminal and st == "failed":
                err = str(meta.get("error_message") or "").strip() or str(job.exc_info or "").strip()
                obj["error"] = err.splitlines()[0][:500] if err else None
        except Exception:
            obj["error"] = None

        return obj, terminal

    active_items: list[dict] = []
    terminal_moved: list[dict] = []
    for s in raw or []:
        try:
            obj = json.loads(s)
            if not isinstance(obj, dict):
                continue
            obj2, terminal = _enrich(obj)
            if terminal:
                terminal_moved.append(obj2)
            else:
                active_items.append(obj2)
        except Exception:
            continue

    # Move terminal jobs out of active queue into history (best-effort), and keep the active list clean.
    try:
        r = get_redis()
        if terminal_moved:
            for it in terminal_moved:
                r.lpush("admin:import_jobs_history", json.dumps(it, ensure_ascii=False))
            r.ltrim("admin:import_jobs_history", 0, 199)
            r.expire("admin:import_jobs_history", 60 * 60 * 24 * 30)

        r.delete("admin:import_jobs")
        for it in active_items[:200]:
            r.rpush("admin:import_jobs", json.dumps(it, ensure_ascii=False))
        r.ltrim("admin:import_jobs", 0, 199)
        r.expire("admin:import_jobs", 60 * 60 * 24 * 30)
    except Exception:
        pass

    items_out = active_items[:take]
    out: dict[str, object] = {"items": items_out}
    if include_terminal:
        hist_items: list[dict] = []
        for s in raw_hist or []:
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    hist_items.append(obj)
            except Exception:
                continue
        out["history"] = hist_items[:take]
    return out


@router.post("/import-jobs/{job_id}/retry")
def retry_import_job(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
):
    # Find import meta in Redis history by job_id.
    try:
        r = get_redis()
        raw = r.lrange("admin:import_jobs", 0, 200)
        raw_hist = r.lrange("admin:import_jobs_history", 0, 200)
    except Exception:
        raw = []
        raw_hist = []

    meta: dict | None = None
    for s in list(raw or []) + list(raw_hist or []):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict) and str(obj.get("job_id") or "") == str(job_id):
                meta = obj
                break
        except Exception:
            continue

    if not meta:
        raise HTTPException(status_code=404, detail="import job meta not found")

    object_key = str(meta.get("object_key") or "").strip()
    if not object_key:
        raise HTTPException(status_code=400, detail="import job has no object_key")

    fingerprint = ""
    try:
        ensure_bucket_exists()
        s3 = get_s3_client()
        head = s3.head_object(Bucket=settings.s3_bucket, Key=object_key)
        etag = str(head.get("ETag") or "").strip().strip('"')
        size = str(head.get("ContentLength") or "").strip()
        if etag and size:
            fingerprint = f"{etag}:{size}"
    except Exception:
        fingerprint = ""

    title = str(meta.get("title") or "").strip() or None

    # Product rule: module should appear immediately in list as hidden while import/regen runs.
    stub_module = None
    try:
        src_fn = str(meta.get("source_filename") or "").strip() or ""
        stub_title = str(title or "").strip() or src_fn or "Модуль"
        if stub_title.lower().endswith(".zip"):
            stub_title = stub_title[:-4]
        stub_title = stub_title.strip() or "Модуль"

        final_quiz = Quiz(type=QuizType.final, pass_threshold=70, time_limit=None, attempts_limit=3)
        db.add(final_quiz)
        db.flush()
        stub_module = Module(
            title=stub_title,
            description=f"Материалы модуля «{stub_title}».",
            difficulty=1,
            category="Обучение",
            is_active=False,
            final_quiz_id=final_quiz.id,
        )
        db.add(stub_module)
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        stub_module = None

    q = get_queue("corelms")
    job = q.enqueue(
        import_module_zip_job,
        s3_object_key=object_key,
        title=title,
        source_filename=(str(meta.get("source_filename") or "").strip() or None),
        actor_user_id=str(current.id),
        module_id=str(stub_module.id) if stub_module is not None else None,
        job_timeout=60 * 60 * 3,
        result_ttl=60 * 60 * 24,
        failure_ttl=60 * 60 * 24,
    )

    try:
        jm = dict(job.meta or {})
        jm["job_kind"] = "import"
        if stub_module is not None:
            jm["module_id"] = str(stub_module.id)
            jm["module_title"] = str(stub_module.title)
        if fingerprint:
            jm["import_fingerprint"] = fingerprint
        job.meta = jm
        job.save_meta()
    except Exception:
        pass

    if fingerprint:
        try:
            r = get_redis()
            r.set(f"admin:import_enqueued_by_fingerprint:{fingerprint}", str(job.id))
            r.expire(f"admin:import_enqueued_by_fingerprint:{fingerprint}", 60 * 60 * 6)
            if stub_module is not None:
                r.set(f"admin:import_fingerprint_by_module_id:{str(stub_module.id)}", fingerprint)
                r.expire(f"admin:import_fingerprint_by_module_id:{str(stub_module.id)}", 60 * 60 * 24 * 30)
        except Exception:
            pass

    return {
        "ok": True,
        "job_id": job.id,
        "module_id": str(stub_module.id) if stub_module is not None else None,
    }


@router.get("/jobs/{job_id}")
def job_status(
    job_id: str,
    _: User = Depends(require_roles(UserRole.admin)),
):
    job = fetch_job(job_id)
    if job is None:
        return {
            "id": str(job_id),
            "status": "missing",
            "enqueued_at": None,
            "started_at": None,
            "ended_at": None,
            "job_kind": None,
            "module_id": None,
            "module_title": None,
            "target_questions": None,
            "stage": "missing",
            "stage_at": None,
            "stage_started_at": None,
            "stage_durations_s": None,
            "job_started_at": None,
            "detail": None,
            "error_code": "JOB_NOT_FOUND",
            "error_class": None,
            "error_hint": "Задача уже удалена из очереди (TTL) или была очищена. Обновите историю.",
            "error_message": "job not found",
            "cancel_requested": False,
            "cancel_requested_at": None,
            "result": None,
            "error": "job not found",
        }

    status = job.get_status(refresh=True)
    meta = dict(job.meta or {})

    error_summary = None
    try:
        if status == "failed":
            error_summary = str(meta.get("error_message") or "").strip() or str(job.exc_info or "").strip()
            if error_summary:
                error_summary = error_summary.splitlines()[0][:500]
    except Exception:
        error_summary = None

    result_payload = None
    try:
        if status == "finished":
            result_payload = job.result
    except Exception:
        result_payload = None

    resp: dict[str, object] = {
        "id": job.id,
        "status": status,
        "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        "job_kind": meta.get("job_kind"),
        "module_id": meta.get("module_id"),
        "module_title": meta.get("module_title"),
        "target_questions": meta.get("target_questions"),
        "stage": meta.get("stage"),
        "stage_at": meta.get("stage_at"),
        "stage_started_at": meta.get("stage_started_at"),
        "stage_durations_s": meta.get("stage_durations_s"),
        "job_started_at": meta.get("job_started_at"),
        "detail": meta.get("detail"),
        "error_code": meta.get("error_code"),
        "error_class": meta.get("error_class"),
        "error_hint": meta.get("error_hint"),
        "error_message": meta.get("error_message"),
        "cancel_requested": bool(meta.get("cancel_requested")),
        "cancel_requested_at": meta.get("cancel_requested_at"),
        "result": result_payload,
        "error": error_summary,
    }
    return resp


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    _: User = Depends(require_roles(UserRole.admin)),
):
    job = fetch_job(job_id)
    if job is None:
        return {"ok": True, "missing": True}

    try:
        kind = str((job.meta or {}).get("job_kind") or "").strip().lower()
    except Exception:
        kind = ""
    if kind and kind != "regen":
        raise HTTPException(status_code=409, detail="job is not cancellable")

    prev_status = job.get_status(refresh=True)

    # Product rule:
    # - Import jobs: cancellable anytime (best-effort), worker will stop at checkpoints.
    # - Regen jobs: cancellable anytime (best-effort), worker will stop at checkpoints.

    try:
        meta = dict(job.meta or {})
        meta["cancel_requested"] = True
        meta["cancel_requested_at"] = datetime.utcnow().isoformat()
        job.meta = meta
        job.save_meta()
    except Exception:
        pass

    # Best-effort immediate cancel (works for queued; may be ignored for started depending on backend).
    try:
        job.cancel()
    except Exception:
        pass

    # Release import enqueue locks so the user can re-enqueue immediately.
    try:
        r = get_redis()
        meta = dict(job.meta or {})
        obj_key = str(meta.get("import_object_key") or "").strip()
        if obj_key:
            r.delete(f"admin:import_enqueued_by_object_key:{obj_key}")
        norm_title = str(meta.get("import_title_norm") or "").strip()
        if norm_title:
            r.delete(f"admin:import_enqueued_by_title:{norm_title}")
        fp = str(meta.get("import_fingerprint") or "").strip()
        if fp:
            r.delete(f"admin:import_enqueued_by_fingerprint:{fp}")
    except Exception:
        pass

    # IMPORTANT: do NOT delete the source ZIP from storage on cancel.
    # Product requirement: upload to storage first, then allow resume/enqueue without re-upload.

    # Best-effort cleanup of any objects uploaded by the job during import.
    try:
        uploaded_keys = list((job.meta or {}).get("uploaded_keys") or [])
    except Exception:
        uploaded_keys = []
    if uploaded_keys:
        try:
            ensure_bucket_exists()
            s3 = get_s3_client()
            for k in uploaded_keys:
                try:
                    kk = str(k or "").strip()
                    if kk:
                        s3.delete_object(Bucket=settings.s3_bucket, Key=kk)
                except Exception:
                    continue
        except Exception:
            pass

    return {"ok": True, "status": prev_status, "job_id": job.id}


@router.post("/content/migrate-legacy")
def migrate_legacy_content(
    request: Request,
    limit: int = 200,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_migrate_legacy_content", limit=10, window_seconds=60),
):
    q = get_queue("corelms")
    job = q.enqueue(migrate_legacy_submodule_content_job, limit=int(limit or 200))

    audit_log(
        db=db,
        request=request,
        event_type="admin_migrate_legacy_content",
        actor_user_id=current.id,
        meta={"job_id": job.id, "limit": int(limit or 200)},
    )
    db.commit()

    return {"ok": True, "job_id": job.id}


@router.post("/modules", response_model=ModuleCreateResponse)
def create_module(
    request: Request,
    body: ModuleCreateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_create_module", limit=30, window_seconds=60),
):
    m = Module(
        title=body.title,
        description=body.description,
        difficulty=body.difficulty,
        category=body.category,
        is_active=body.is_active,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    audit_log(
        db=db,
        request=request,
        event_type="admin_create_module",
        actor_user_id=current.id,
        meta={"module_id": str(m.id), "title": m.title},
    )
    db.commit()
    return {"id": str(m.id)}


@router.delete("/modules/{module_id}")
def delete_module(
    request: Request,
    module_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_delete_module", limit=30, window_seconds=60),
):
    mid = _uuid(module_id, field="module_id")
    m = db.scalar(select(Module).where(Module.id == mid))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    sub_ids = list(db.scalars(select(Submodule.id).where(Submodule.module_id == m.id)).all())
    quiz_ids = list(db.scalars(select(Submodule.quiz_id).where(Submodule.module_id == m.id)).all())
    if m.final_quiz_id:
        quiz_ids.append(m.final_quiz_id)

    quiz_ids = [qid for qid in quiz_ids if qid is not None]
    quiz_ids = list({qid for qid in quiz_ids})

    # Asset ids: linked lesson assets + module-level assets by convention.
    asset_ids: set[uuid.UUID] = set()
    if sub_ids:
        rows = db.scalars(select(SubmoduleAssetMap.asset_id).where(SubmoduleAssetMap.submodule_id.in_(sub_ids))).all()
        for aid in rows:
            if aid:
                asset_ids.add(aid)

    prefix = f"modules/{module_id}/_module/"
    module_level_assets = db.scalars(select(ContentAsset.id).where(ContentAsset.object_key.like(prefix + "%"))).all()
    for aid in module_level_assets:
        if aid:
            asset_ids.add(aid)

    # Break FK module.final_quiz_id -> quizzes
    m.final_quiz_id = None
    db.flush()

    if asset_ids:
        db.execute(delete(LearningEvent).where(LearningEvent.ref_id.in_(list(asset_ids))))

    if sub_ids:
        db.execute(delete(LearningEvent).where(LearningEvent.ref_id.in_(sub_ids)))
        db.execute(delete(SubmoduleAssetMap).where(SubmoduleAssetMap.submodule_id.in_(sub_ids)))

        # submodules.quiz_id is NOT NULL in some DB schemas. We must delete submodules
        # before deleting quizzes to avoid FK violations.
        db.execute(text("DELETE FROM submodules WHERE module_id = :mid"), {"mid": str(m.id)})

    if quiz_ids:
        attempt_ids = list(db.scalars(select(QuizAttempt.id).where(QuizAttempt.quiz_id.in_(quiz_ids))).all())
        if attempt_ids:
            db.execute(
                text("DELETE FROM quiz_attempt_answers WHERE attempt_id IN :ids").bindparams(
                    bindparam("ids", expanding=True, value=attempt_ids)
                )
            )
        db.execute(delete(QuizAttempt).where(QuizAttempt.quiz_id.in_(quiz_ids)))

        db.execute(delete(Question).where(Question.quiz_id.in_(quiz_ids)))
        db.execute(delete(Quiz).where(Quiz.id.in_(quiz_ids)))

    if asset_ids:
        db.execute(delete(ContentAsset).where(ContentAsset.id.in_(list(asset_ids))))

    # Legacy table still exists in DB.
    db.execute(text("DELETE FROM module_skill_map WHERE module_id = :mid"), {"mid": str(m.id)})
    db.execute(text("DELETE FROM modules WHERE id = :mid"), {"mid": str(m.id)})

    audit_log(
        db=db,
        request=request,
        event_type="admin_delete_module",
        actor_user_id=current.id,
        meta={"module_id": str(mid), "module_title": m.title},
    )
    db.commit()

    # Best-effort: release fingerprint idempotency key so the same ZIP can be imported again immediately.
    try:
        r = get_redis()
        fp = str(r.get(f"admin:import_fingerprint_by_module_id:{str(mid)}") or "").strip()
        if fp:
            r.delete(f"admin:import_enqueued_by_fingerprint:{fp}")
        r.delete(f"admin:import_fingerprint_by_module_id:{str(mid)}")
    except Exception:
        pass

    _delete_s3_prefix_best_effort(prefix=f"modules/{module_id}/")

    return {"ok": True}


@router.get("/modules")
def list_modules_admin(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    mods = db.scalars(select(Module).order_by(Module.title)).all()

    stats_by_module: dict[str, dict[str, int]] = {}
    needs_regen_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("needs_regen:%"))
    needs_ai_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("needs_ai:%"))
    fallback_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("%fallback%"))
    ai_cond = (Question.concept_tag.is_not(None)) & (
        Question.concept_tag.like("ai:%") | Question.concept_tag.like("regen:%")
    )
    heur_cond = (Question.concept_tag.is_not(None)) & (
        Question.concept_tag.like("heur:%") | Question.concept_tag.like("needs_ai:heur:%")
    )

    lesson_rows = (
        db.execute(
            select(
                Submodule.module_id.label("module_id"),
                func.count(Question.id).label("total_current"),
                func.sum(case(((needs_regen_cond | needs_ai_cond), 1), else_=0)).label("needs_regen_current"),
                func.sum(case((fallback_cond, 1), else_=0)).label("fallback_current"),
                func.sum(case((ai_cond, 1), else_=0)).label("ai_current"),
                func.sum(case((heur_cond, 1), else_=0)).label("heur_current"),
            )
            .select_from(Submodule)
            .join(Question, Question.quiz_id == Submodule.quiz_id, isouter=True)
            .where(Submodule.quiz_id.is_not(None))
            .group_by(Submodule.module_id)
        )
        .all()
    )

    final_rows = (
        db.execute(
            select(
                Module.id.label("module_id"),
                func.count(Question.id).label("total_current"),
                func.sum(case(((needs_regen_cond | needs_ai_cond), 1), else_=0)).label("needs_regen_current"),
                func.sum(case((fallback_cond, 1), else_=0)).label("fallback_current"),
                func.sum(case((ai_cond, 1), else_=0)).label("ai_current"),
                func.sum(case((heur_cond, 1), else_=0)).label("heur_current"),
            )
            .select_from(Module)
            .join(Question, Question.quiz_id == Module.final_quiz_id, isouter=True)
            .where(Module.final_quiz_id.is_not(None))
            .group_by(Module.id)
        )
        .all()
    )

    def _acc(mid: str, row: object) -> None:
        cur = stats_by_module.get(
            mid,
            {
                "total_current": 0,
                "needs_regen_current": 0,
                "fallback_current": 0,
                "ai_current": 0,
                "heur_current": 0,
            },
        )
        cur["total_current"] += int(getattr(row, "total_current", 0) or 0)
        cur["needs_regen_current"] += int(getattr(row, "needs_regen_current", 0) or 0)
        cur["fallback_current"] += int(getattr(row, "fallback_current", 0) or 0)
        cur["ai_current"] += int(getattr(row, "ai_current", 0) or 0)
        cur["heur_current"] += int(getattr(row, "heur_current", 0) or 0)
        stats_by_module[mid] = cur

    for r in lesson_rows:
        _acc(str(r.module_id), r)
    for r in final_rows:
        _acc(str(r.module_id), r)

    return {
        "items": [
            {
                "id": str(m.id),
                "title": str(m.title),
                "is_active": bool(m.is_active),
                "category": m.category,
                "difficulty": int(m.difficulty or 1),
                "final_quiz_id": str(m.final_quiz_id) if getattr(m, "final_quiz_id", None) else None,
                "question_quality": stats_by_module.get(
                    str(m.id),
                    {
                        "total_current": 0,
                        "needs_regen_current": 0,
                        "fallback_current": 0,
                        "ai_current": 0,
                        "heur_current": 0,
                    },
                ),
            }
            for m in mods
        ]
    }


class ModuleVisibilityRequest(BaseModel):
    is_active: bool


@router.post("/modules/{module_id}/visibility")
def set_module_visibility(
    request: Request,
    module_id: str,
    body: ModuleVisibilityRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_set_module_visibility", limit=60, window_seconds=60),
):
    mid = _uuid(module_id, field="module_id")
    m = db.scalar(select(Module).where(Module.id == mid))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    target = bool(body.is_active)

    if target:
        needs_regen_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("needs_regen:%"))
        lesson_quiz_ids = list(
            db.scalars(select(Submodule.quiz_id).where(Submodule.module_id == m.id).where(Submodule.quiz_id.is_not(None))).all()
        )
        if getattr(m, "final_quiz_id", None):
            lesson_quiz_ids.append(m.final_quiz_id)
        lesson_quiz_ids = [qid for qid in lesson_quiz_ids if qid is not None]

        needs = 0
        if lesson_quiz_ids:
            needs = int(
                db.scalar(select(func.count()).select_from(Question).where(Question.quiz_id.in_(lesson_quiz_ids)).where(needs_regen_cond))
                or 0
            )
        if needs > 0:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "MODULE_NOT_READY",
                    "error_message": "module has needs_regen questions",
                    "error_hint": "Нельзя показать модуль, пока тесты не сгенерированы нейросетью и есть NEEDS REGEN. Запустите РЕГЕН ТЕСТОВ и дождитесь завершения.",
                    "needs_regen": needs,
                },
            )

    m.is_active = target

    audit_log(
        db=db,
        request=request,
        event_type="admin_set_module_visibility",
        actor_user_id=current.id,
        meta={"module_id": str(m.id), "is_active": bool(target)},
    )
    db.commit()
    return {"ok": True, "module_id": str(m.id), "is_active": bool(m.is_active)}


@router.post("/modules/{module_id}/regenerate-quizzes")
def regenerate_module_quizzes(
    request: Request,
    module_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_regenerate_module_quizzes", limit=30, window_seconds=60),
):
    mid = _uuid(module_id, field="module_id")
    m = db.scalar(select(Module).where(Module.id == mid))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    # Product rule: each lesson quiz always has exactly 5 questions.
    tq = 5

    q = get_queue("corelms")
    job = q.enqueue(
        regenerate_module_quizzes_job,
        module_id=str(mid),
        target_questions=tq,
        only_missing=False,
        job_timeout=60 * 60 * 2,
        result_ttl=60 * 60 * 24,
        failure_ttl=60 * 60 * 24,
    )

    # Enrich meta for a better admin UX (/admin/jobs/{id} and unified task panels).
    try:
        meta = dict(job.meta or {})
        meta["job_kind"] = "regen"
        meta["module_id"] = str(mid)
        meta["module_title"] = str(m.title)
        meta["target_questions"] = int(tq)
        job.meta = meta
        job.save_meta()
    except Exception:
        pass

    audit_log(
        db=db,
        request=request,
        event_type="admin_regenerate_module_quizzes",
        actor_user_id=current.id,
        meta={"job_id": job.id, "module_id": str(mid), "target_questions": tq},
    )
    db.commit()

    try:
        r = get_redis()
        meta = {
            "job_id": job.id,
            "module_id": str(mid),
            "module_title": str(m.title),
            "target_questions": int(tq),
            "created_at": datetime.utcnow().isoformat(),
            "actor_user_id": str(current.id),
        }
        r.lpush("admin:regen_jobs", json.dumps(meta, ensure_ascii=False))
        r.ltrim("admin:regen_jobs", 0, 49)
        r.expire("admin:regen_jobs", 60 * 60 * 24 * 30)
    except Exception:
        pass

    return {"ok": True, "job_id": job.id, "module_id": str(mid), "target_questions": tq}


@router.post("/submodules/{submodule_id}/regenerate-quiz")
def regenerate_submodule_quiz(
    request: Request,
    submodule_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_regenerate_submodule_quiz", limit=60, window_seconds=60),
):
    sid = _uuid(submodule_id, field="submodule_id")
    sub = db.scalar(select(Submodule).where(Submodule.id == sid))
    if sub is None:
        raise HTTPException(status_code=404, detail="submodule not found")

    m = db.scalar(select(Module).where(Module.id == sub.module_id))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    tq = 5
    q = get_queue("corelms")
    job = q.enqueue(
        regenerate_submodule_quiz_job,
        submodule_id=str(sid),
        target_questions=tq,
        job_timeout=60 * 60,
        result_ttl=60 * 60 * 24,
        failure_ttl=60 * 60 * 24,
    )

    try:
        meta = dict(job.meta or {})
        meta["job_kind"] = "regen"
        meta["module_id"] = str(m.id)
        meta["module_title"] = str(m.title)
        meta["submodule_id"] = str(sub.id)
        meta["submodule_title"] = str(sub.title or "")
        meta["target_questions"] = int(tq)
        job.meta = meta
        job.save_meta()
    except Exception:
        pass

    audit_log(
        db=db,
        request=request,
        event_type="admin_regenerate_submodule_quiz",
        actor_user_id=current.id,
        meta={"job_id": job.id, "module_id": str(m.id), "submodule_id": str(sub.id), "target_questions": tq},
    )
    db.commit()

    try:
        r = get_redis()
        meta = {
            "job_id": job.id,
            "module_id": str(m.id),
            "module_title": str(m.title),
            "submodule_id": str(sub.id),
            "submodule_title": str(sub.title or ""),
            "target_questions": int(tq),
            "created_at": datetime.utcnow().isoformat(),
            "actor_user_id": str(current.id),
            "source": "submodule_button",
        }
        r.lpush("admin:regen_jobs", json.dumps(meta, ensure_ascii=False))
        r.ltrim("admin:regen_jobs", 0, 49)
        r.expire("admin:regen_jobs", 60 * 60 * 24 * 30)
    except Exception:
        pass

    return {"ok": True, "job_id": job.id, "module_id": str(m.id), "submodule_id": str(sub.id), "target_questions": tq}


@router.get("/regen-jobs")
def list_regen_jobs(
    limit: int = 20,
    include_terminal: bool = False,
    _: User = Depends(require_roles(UserRole.admin)),
):
    take = max(1, min(int(limit or 20), 50))
    include_terminal = bool(include_terminal)
    try:
        r = get_redis()
        raw = r.lrange("admin:regen_jobs", 0, 200)
        raw_hist = r.lrange("admin:regen_jobs_history", 0, 200) if include_terminal else []
    except Exception:
        raw = []
        raw_hist = []

    active_items: list[dict] = []
    terminal_moved: list[dict] = []
    for s in raw or []:
        try:
            obj = json.loads(s)
            if not isinstance(obj, dict):
                continue

            job_id = str(obj.get("job_id") or "").strip()
            job = fetch_job(job_id) if job_id else None
            if job is None:
                obj["status"] = "missing"
                obj["stage"] = "missing"
                obj["error_code"] = obj.get("error_code") or "JOB_NOT_FOUND"
                obj["error_hint"] = obj.get("error_hint") or "Задача уже удалена из очереди (TTL) или была очищена. Обновите историю."
                obj["error_message"] = obj.get("error_message") or "job not found"
                obj["error"] = obj.get("error") or "job not found"
                terminal_items.append(obj)
                continue

            st = str(job.get_status(refresh=True) or "").strip().lower()
            meta = dict(job.meta or {})
            stage = str(meta.get("stage") or "").strip().lower()
            obj["status"] = st
            obj["stage"] = meta.get("stage")
            obj["stage_at"] = meta.get("stage_at")
            obj["detail"] = meta.get("detail")
            obj["error_code"] = meta.get("error_code")
            obj["error_hint"] = meta.get("error_hint")
            obj["error_message"] = meta.get("error_message")
            obj["cancel_requested"] = bool(meta.get("cancel_requested"))
            try:
                if st == "failed":
                    err = str(meta.get("error_message") or "").strip() or str(job.exc_info or "").strip()
                    obj["error"] = err.splitlines()[0][:500] if err else None
            except Exception:
                obj["error"] = None

            terminal = st in {"finished", "failed", "canceled"} or stage == "canceled" or stage == "done"
            if terminal:
                terminal_moved.append(obj)
            else:
                active_items.append(obj)
        except Exception:
            continue

    try:
        r = get_redis()
        if terminal_moved:
            for it in terminal_moved:
                r.lpush("admin:regen_jobs_history", json.dumps(it, ensure_ascii=False))
            r.ltrim("admin:regen_jobs_history", 0, 199)
            r.expire("admin:regen_jobs_history", 60 * 60 * 24 * 30)

        r.delete("admin:regen_jobs")
        for it in active_items[:200]:
            r.rpush("admin:regen_jobs", json.dumps(it, ensure_ascii=False))
        r.ltrim("admin:regen_jobs", 0, 199)
        r.expire("admin:regen_jobs", 60 * 60 * 24 * 30)
    except Exception:
        pass

    items_out = active_items[:take]
    out: dict[str, object] = {"items": items_out}
    if include_terminal:
        hist_items: list[dict] = []
        for s in raw_hist or []:
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    hist_items.append(obj)
            except Exception:
                continue
        out["history"] = hist_items[:take]
    return out


@router.post("/jobs/history/clear")
def clear_admin_job_history(
    request: Request,
    current: User = Depends(require_roles(UserRole.admin)),
):
    try:
        r = get_redis()
        r.delete("admin:import_jobs_history")
        r.delete("admin:regen_jobs")
        r.delete("admin:regen_jobs_history")
    except Exception:
        pass

    try:
        audit_log(
            db=SessionLocal(),
            request=request,
            event_type="admin_clear_job_history",
            actor_user_id=current.id,
            meta={},
        )
    except Exception:
        pass

    return {"ok": True}


@router.get("/modules/needs-regen")
def modules_needs_regen(
    _: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    # Count questions tagged with needs_regen:* per module.
    # Uses outer joins to return 0 for modules without flagged questions.
    needs_regen_cond = (Question.concept_tag.is_not(None)) & (Question.concept_tag.like("needs_regen:%"))

    rows = (
        db.execute(
            select(
                Module.id.label("module_id"),
                func.sum(case((needs_regen_cond, 1), else_=0)).label("needs_regen_questions"),
            )
            .select_from(Module)
            .join(Submodule, Submodule.module_id == Module.id, isouter=True)
            .join(Question, Question.quiz_id == Submodule.quiz_id, isouter=True)
            .group_by(Module.id)
        )
        .all()
    )

    items: list[dict[str, object]] = []
    for r in rows:
        items.append(
            {
                "module_id": str(r.module_id),
                "needs_regen_questions": int(r.needs_regen_questions or 0),
            }
        )
    return {"items": items}


@router.post("/quizzes", response_model=QuizCreateResponse)
def create_quiz(
    request: Request,
    body: QuizCreateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_create_quiz", limit=30, window_seconds=60),
):
    try:
        qt = QuizType(body.type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid quiz type") from e

    q = Quiz(
        type=qt,
        pass_threshold=body.pass_threshold,
        time_limit=body.time_limit,
        attempts_limit=body.attempts_limit,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    audit_log(
        db=db,
        request=request,
        event_type="admin_create_quiz",
        actor_user_id=current.id,
        meta={"quiz_id": str(q.id), "type": getattr(q.type, "value", str(q.type))},
    )
    db.commit()
    return {"id": str(q.id)}


@router.post("/questions", response_model=QuestionCreateResponse)
def create_question(
    request: Request,
    body: QuestionCreateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_create_question", limit=60, window_seconds=60),
):
    quiz_id = _uuid(body.quiz_id, field="quiz_id")
    quiz = db.scalar(select(Quiz).where(Quiz.id == quiz_id))
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")

    try:
        t = QuestionType(body.type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid question type") from e

    correct_answer = _normalize_correct_answer_for_type(qtype=getattr(t, "value", str(t)), raw=str(body.correct_answer))

    question = Question(
        quiz_id=quiz.id,
        type=t,
        difficulty=body.difficulty,
        prompt=body.prompt,
        correct_answer=correct_answer,
        explanation=body.explanation,
        concept_tag=body.concept_tag,
        variant_group=body.variant_group,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    audit_log(
        db=db,
        request=request,
        event_type="admin_create_question",
        actor_user_id=current.id,
        meta={"quiz_id": str(quiz.id), "question_id": str(question.id), "type": getattr(question.type, "value", str(question.type))},
    )
    db.commit()
    return {"id": str(question.id)}


@router.get("/quizzes/{quiz_id}/questions", response_model=QuestionsListResponse)
def list_questions_for_quiz(
    request: Request,
    quiz_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
):
    qid = _uuid(quiz_id, field="quiz_id")
    quiz = db.scalar(select(Quiz).where(Quiz.id == qid))
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")

    questions = db.scalars(select(Question).where(Question.quiz_id == quiz.id).order_by(Question.id)).all()
    audit_log(
        db=db,
        request=request,
        event_type="admin_list_questions",
        actor_user_id=current.id,
        meta={"quiz_id": str(quiz.id), "count": len(questions)},
    )
    db.commit()

    def _q_public(q: Question) -> dict[str, object]:
        return {
            "id": str(q.id),
            "quiz_id": str(q.quiz_id),
            "type": getattr(getattr(q, "type", None), "value", str(getattr(q, "type", ""))),
            "difficulty": int(getattr(q, "difficulty", 1) or 1),
            "prompt": str(getattr(q, "prompt", "") or ""),
            "correct_answer": str(getattr(q, "correct_answer", "") or ""),
            "explanation": getattr(q, "explanation", None),
            "concept_tag": getattr(q, "concept_tag", None),
            "variant_group": getattr(q, "variant_group", None),
        }

    return {"items": [_q_public(q) for q in questions]}


@router.get("/questions/{question_id}", response_model=QuestionPublic)
def get_question(
    request: Request,
    question_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
):
    qid = _uuid(question_id, field="question_id")
    q = db.scalar(select(Question).where(Question.id == qid))
    if q is None:
        raise HTTPException(status_code=404, detail="question not found")

    audit_log(
        db=db,
        request=request,
        event_type="admin_get_question",
        actor_user_id=current.id,
        meta={"question_id": str(q.id), "quiz_id": str(q.quiz_id)},
    )
    db.commit()

    return {
        "id": str(q.id),
        "quiz_id": str(q.quiz_id),
        "type": getattr(getattr(q, "type", None), "value", str(getattr(q, "type", ""))),
        "difficulty": int(getattr(q, "difficulty", 1) or 1),
        "prompt": str(getattr(q, "prompt", "") or ""),
        "correct_answer": str(getattr(q, "correct_answer", "") or ""),
        "explanation": getattr(q, "explanation", None),
        "concept_tag": getattr(q, "concept_tag", None),
        "variant_group": getattr(q, "variant_group", None),
    }


@router.patch("/questions/{question_id}", response_model=QuestionUpdateResponse)
def update_question(
    request: Request,
    question_id: str,
    body: QuestionUpdateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_update_question", limit=120, window_seconds=60),
):
    qid = _uuid(question_id, field="question_id")
    q = db.scalar(select(Question).where(Question.id == qid))
    if q is None:
        raise HTTPException(status_code=404, detail="question not found")

    before = {
        "type": getattr(getattr(q, "type", None), "value", str(getattr(q, "type", ""))),
        "difficulty": int(getattr(q, "difficulty", 1) or 1),
        "prompt": str(getattr(q, "prompt", "") or ""),
        "correct_answer": str(getattr(q, "correct_answer", "") or ""),
        "explanation": getattr(q, "explanation", None),
        "concept_tag": getattr(q, "concept_tag", None),
        "variant_group": getattr(q, "variant_group", None),
    }

    if body.type is not None:
        try:
            q.type = QuestionType(body.type)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid question type") from e
    if body.difficulty is not None:
        q.difficulty = max(1, int(body.difficulty))
    if body.prompt is not None:
        q.prompt = str(body.prompt)
    if body.correct_answer is not None:
        raw = str(body.correct_answer)
        # Product UX: accept any separators/case/order and store canonical form.
        # Also infer type from letters when admin didn't explicitly set type.
        letters = set()
        try:
            _, letters = _normalize_abcd_answer(raw)
        except Exception:
            letters = set()

        if body.type is None:
            try:
                if getattr(q.type, "value", str(q.type)) != "case":
                    if len(letters) >= 2:
                        q.type = QuestionType.multi
                    elif len(letters) == 1:
                        q.type = QuestionType.single
            except Exception:
                pass

        q.correct_answer = _normalize_correct_answer_for_type(qtype=getattr(q.type, "value", str(q.type)), raw=raw)
    if body.explanation is not None:
        q.explanation = body.explanation
    if body.concept_tag is not None:
        q.concept_tag = body.concept_tag
    if body.variant_group is not None:
        q.variant_group = body.variant_group

    db.add(q)
    db.commit()
    db.refresh(q)

    after = {
        "type": getattr(getattr(q, "type", None), "value", str(getattr(q, "type", ""))),
        "difficulty": int(getattr(q, "difficulty", 1) or 1),
        "prompt": str(getattr(q, "prompt", "") or ""),
        "correct_answer": str(getattr(q, "correct_answer", "") or ""),
        "explanation": getattr(q, "explanation", None),
        "concept_tag": getattr(q, "concept_tag", None),
        "variant_group": getattr(q, "variant_group", None),
    }

    audit_log(
        db=db,
        request=request,
        event_type="admin_update_question",
        actor_user_id=current.id,
        meta={"question_id": str(q.id), "quiz_id": str(q.quiz_id), "before": before, "after": after},
    )
    db.commit()

    return {
        "ok": True,
        "item": {
            "id": str(q.id),
            "quiz_id": str(q.quiz_id),
            "type": after["type"],
            "difficulty": int(after["difficulty"]),
            "prompt": str(after["prompt"]),
            "correct_answer": str(after["correct_answer"]),
            "explanation": after["explanation"],
            "concept_tag": after["concept_tag"],
            "variant_group": after["variant_group"],
        },
    }


@router.delete("/questions/{question_id}")
def delete_question(
    request: Request,
    question_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_delete_question", limit=60, window_seconds=60),
):
    qid = _uuid(question_id, field="question_id")
    q = db.scalar(select(Question).where(Question.id == qid))
    if q is None:
        raise HTTPException(status_code=404, detail="question not found")

    # Delete dependent attempt answers first to keep FK integrity.
    deleted_answers = db.execute(delete(QuizAttemptAnswer).where(QuizAttemptAnswer.question_id == q.id)).rowcount
    db.execute(delete(Question).where(Question.id == q.id))
    db.commit()

    audit_log(
        db=db,
        request=request,
        event_type="admin_delete_question",
        actor_user_id=current.id,
        meta={"question_id": str(q.id), "quiz_id": str(q.quiz_id), "deleted_attempt_answers": int(deleted_answers or 0)},
    )
    db.commit()

    return {"ok": True}


@router.post("/submodules", response_model=SubmoduleCreateResponse)
def create_submodule(
    request: Request,
    body: SubmoduleCreateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_create_submodule", limit=30, window_seconds=60),
):
    module_id = _uuid(body.module_id, field="module_id")
    quiz_id = _uuid(body.quiz_id, field="quiz_id")

    m = db.scalar(select(Module).where(Module.id == module_id))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    q = db.scalar(select(Quiz).where(Quiz.id == quiz_id))
    if q is None:
        raise HTTPException(status_code=404, detail="quiz not found")

    s = Submodule(module_id=m.id, title=body.title, order=body.order, quiz_id=q.id, content="")
    db.add(s)
    db.commit()
    db.refresh(s)
    audit_log(
        db=db,
        request=request,
        event_type="admin_create_submodule",
        actor_user_id=current.id,
        meta={"module_id": str(m.id), "submodule_id": str(s.id), "quiz_id": str(q.id), "order": int(s.order)},
    )
    db.commit()
    return {"id": str(s.id)}


@router.post("/submodules/link-asset", response_model=LinkAssetToSubmoduleResponse)
def link_asset_to_submodule(
    request: Request,
    body: LinkAssetToSubmoduleRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_link_asset", limit=60, window_seconds=60),
):
    submodule_id = _uuid(body.submodule_id, field="submodule_id")
    asset_id = _uuid(body.asset_id, field="asset_id")

    existing = db.scalar(
        select(SubmoduleAssetMap).where(
            SubmoduleAssetMap.submodule_id == submodule_id,
            SubmoduleAssetMap.asset_id == asset_id,
        )
    )
    if existing is not None:
        return {"ok": True}

    link = SubmoduleAssetMap(submodule_id=submodule_id, asset_id=asset_id, order=body.order)
    db.add(link)
    db.commit()
    audit_log(
        db=db,
        request=request,
        event_type="admin_link_asset_to_submodule",
        actor_user_id=current.id,
        meta={"submodule_id": str(submodule_id), "asset_id": str(asset_id), "order": int(body.order)},
    )
    db.commit()
    return {"ok": True}


@router.post("/assignments", response_model=AssignmentCreateResponse)
def create_assignment(
    request: Request,
    body: AssignmentCreateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_create_assignment", limit=30, window_seconds=60),
):
    assigned_to = _uuid(body.assigned_to, field="assigned_to")
    target_id = _uuid(body.target_id, field="target_id")

    try:
        t = AssignmentType(body.type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid assignment type") from e

    deadline_dt = None
    if body.deadline:
        try:
            deadline_dt = datetime.fromisoformat(body.deadline)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid deadline") from e

    a = Assignment(
        assigned_by=current.id,
        assigned_to=assigned_to,
        type=t,
        target_id=target_id,
        priority=body.priority,
        deadline=deadline_dt,
        status=AssignmentStatus.pending,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    audit_log(
        db=db,
        request=request,
        event_type="admin_create_assignment",
        actor_user_id=current.id,
        target_user_id=assigned_to,
        meta={"assignment_id": str(a.id), "type": a.type.value, "target_id": str(a.target_id), "deadline": body.deadline},
    )
    db.commit()
    return {"id": str(a.id)}


@router.get("/modules/{module_id}/answers")
def get_module_answers(
    module_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    """Return correct answers for all questions in a module (admin-only, for demo/QA)."""
    try:
        mod_uuid = uuid.UUID(module_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid module_id") from e

    # Verify module exists
    mod = db.scalar(select(Module).where(Module.id == mod_uuid))
    if mod is None:
        raise HTTPException(status_code=404, detail="module not found")

    # Fetch all questions via submodule->quiz->question
    rows = db.execute(
        text(
            """
            SELECT
                q.id AS question_id,
                q.prompt,
                q.type,
                q.correct_answer,
                q.variant_group,
                qz.id AS quiz_id,
                sm.id AS submodule_id,
                sm.title AS submodule_title,
                sm.order AS submodule_order
            FROM questions q
            JOIN quizzes qz ON q.quiz_id = qz.id
            JOIN submodules sm ON qz.id = sm.quiz_id
            WHERE sm.module_id = :module_id
            ORDER BY sm.order, qz.id, q.id
            """
        ),
        {"module_id": mod_uuid}
    ).fetchall()

    answers = [
        {
            "question_id": str(row.question_id),
            "quiz_id": str(row.quiz_id),
            "submodule_id": str(row.submodule_id),
            "submodule_title": row.submodule_title,
            "submodule_order": int(row.submodule_order),
            "prompt": row.prompt,
            "type": row.type,
            "correct_answer": row.correct_answer,
            "variant_group": row.variant_group,
        }
        for row in rows
    ]

    return {"module_id": module_id, "module_title": mod.title, "answers": answers}


@router.get("/users")
def list_admin_modules(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    rows = db.scalars(select(User).order_by(User.name)).all()

    modules = db.scalars(select(Module).where(Module.is_active == True).order_by(Module.title)).all()
    module_by_id: dict[uuid.UUID, Module] = {m.id: m for m in modules}

    sub_rows = db.execute(
        select(Submodule.module_id, Submodule.id, Submodule.quiz_id)
        .where(Submodule.module_id.in_([m.id for m in modules]))
        .order_by(Submodule.module_id, Submodule.order)
    ).all()

    quiz_to_module: dict[uuid.UUID, uuid.UUID] = {}
    steps_by_module: dict[uuid.UUID, int] = defaultdict(int)
    all_quiz_ids: set[uuid.UUID] = set()
    all_sub_ids: set[uuid.UUID] = set()
    for mid, sid, qid in sub_rows:
        quiz_to_module[qid] = mid
        steps_by_module[mid] += 1
        all_quiz_ids.add(qid)
        all_sub_ids.add(sid)

    for m in modules:
        if m.final_quiz_id:
            quiz_to_module[m.final_quiz_id] = m.id
            steps_by_module[m.id] += 1
            all_quiz_ids.add(m.final_quiz_id)

    user_ids = [u.id for u in rows]

    passed_by_user_module: dict[tuple[uuid.UUID, uuid.UUID], int] = defaultdict(int)
    if user_ids and all_quiz_ids:
        passed_rows = db.execute(
            select(QuizAttempt.user_id, QuizAttempt.quiz_id)
            .where(
                QuizAttempt.user_id.in_(user_ids),
                QuizAttempt.quiz_id.in_(list(all_quiz_ids)),
                QuizAttempt.passed == True,
            )
            .group_by(QuizAttempt.user_id, QuizAttempt.quiz_id)
        ).all()
        for uid, qid in passed_rows:
            mid = quiz_to_module.get(qid)
            if mid is None:
                continue
            passed_by_user_module[(uid, mid)] += 1

    read_by_user_module: dict[tuple[uuid.UUID, uuid.UUID], int] = defaultdict(int)
    if user_ids and all_sub_ids:
        # Legacy meta=="read" or JSON {"action":"read"}
        read_rows = db.execute(
            select(LearningEvent.user_id, Submodule.module_id, LearningEvent.ref_id, LearningEvent.meta)
            .join(Submodule, Submodule.id == LearningEvent.ref_id)
            .where(
                LearningEvent.user_id.in_(user_ids),
                LearningEvent.type == LearningEventType.submodule_opened,
                LearningEvent.ref_id.in_(list(all_sub_ids)),
                LearningEvent.meta.is_not(None),
            )
        ).all()

        seen: set[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = set()
        for uid, mid, sid, meta in read_rows:
            key = (uid, mid, sid)
            if key in seen:
                continue
            ok = False
            try:
                if str(meta).strip().lower() == "read":
                    ok = True
                else:
                    obj = json.loads(str(meta))
                    if isinstance(obj, dict) and str(obj.get("action") or "").strip().lower() == "read":
                        ok = True
            except Exception:
                ok = False
            if not ok:
                continue
            seen.add(key)
            read_by_user_module[(uid, mid)] += 1

    def _progress_summary_for_user(u: User) -> dict[str, object]:
        completed_count = 0
        in_progress_count = 0
        current: dict[str, object] | None = None
        current_pct = -1

        for mid, m in module_by_id.items():
            total = int(steps_by_module.get(mid) or 0)
            passed = int(passed_by_user_module.get((u.id, mid)) or 0)
            read = int(read_by_user_module.get((u.id, mid)) or 0)

            if total <= 0:
                continue

            completed = passed >= total and total > 0
            started = passed > 0 or read > 0
            pct = int(round((passed / total) * 100)) if total > 0 else 0
            pct = max(0, min(100, pct))

            if completed:
                completed_count += 1
                continue

            if started:
                in_progress_count += 1
                if pct > current_pct:
                    current_pct = pct
                    current = {
                        "module_id": str(mid),
                        "title": m.title,
                        "total": total,
                        "passed": passed,
                        "percent": pct,
                    }

        return {
            "completed_count": int(completed_count),
            "in_progress_count": int(in_progress_count),
            "current": current,
        }

    return {
        "items": [
            {
                "id": str(u.id),
                "name": u.name,
                "role": u.role.value,
                "position": u.position,
                "xp": int(u.xp or 0),
                "level": int(u.level or 0),
                "streak": int(u.streak or 0),
                "last_activity_at": u.last_activity_at.isoformat() if getattr(u, "last_activity_at", None) else None,
                "created_at": u.created_at.isoformat() if getattr(u, "created_at", None) else None,
                "progress_summary": _progress_summary_for_user(u),
            }
            for u in rows
        ]
    }


@router.get("/users/{user_id}")
def get_user_detail(
    user_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    uid = _uuid(user_id, field="user_id")
    u = db.scalar(select(User).where(User.id == uid))
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")

    assignments_total = db.scalar(select(func.count()).select_from(Assignment).where(Assignment.assigned_to == uid)) or 0
    assignments_completed = (
        db.scalar(
            select(func.count())
            .select_from(Assignment)
            .where(Assignment.assigned_to == uid)
            .where(Assignment.status == AssignmentStatus.completed)
        )
        or 0
    )
    attempts_total = db.scalar(select(func.count()).select_from(QuizAttempt).where(QuizAttempt.user_id == uid)) or 0
    attempts_passed = (
        db.scalar(select(func.count()).select_from(QuizAttempt).where(QuizAttempt.user_id == uid).where(QuizAttempt.passed == True))
        or 0
    )
    events_total = db.scalar(select(func.count()).select_from(LearningEvent).where(LearningEvent.user_id == uid)) or 0

    modules = db.scalars(select(Module).where(Module.is_active == True).order_by(Module.title)).all()
    module_ids = [m.id for m in modules]
    progress_map = LearningService(db).get_modules_progress(u, module_ids)

    completed_modules: list[dict[str, object]] = []
    in_progress_modules: list[dict[str, object]] = []
    for m in modules:
        prog = progress_map.get(m.id) or {}
        total = int(prog.get("total") or 0)
        passed = int(prog.get("passed") or 0)
        completed = bool(prog.get("completed") or False)
        submods = prog.get("submodules") or []
        started = passed > 0 or any(bool(x.get("read")) for x in submods if isinstance(x, dict))

        pct = 0
        if total > 0:
            pct = int(round((passed / total) * 100))

        item = {
            "module_id": str(m.id),
            "title": m.title,
            "total": total,
            "passed": passed,
            "percent": pct,
            "completed": completed,
        }

        if completed:
            completed_modules.append(item)
        elif started:
            in_progress_modules.append(item)

    # Fetch recent history (last 20 events)
    recent_events = db.scalars(
        select(LearningEvent)
        .where(LearningEvent.user_id == uid)
        .order_by(LearningEvent.created_at.desc())
        .limit(20)
    ).all()

    history = []
    for ev in recent_events:
        et = None
        try:
            if hasattr(ev, "event_type"):
                et = getattr(ev, "event_type")
            else:
                et = getattr(ev, "type")
        except Exception:
            et = None

        meta_val: object = {}
        try:
            raw_meta = getattr(ev, "meta", None)
            if raw_meta is None:
                meta_val = {}
            elif isinstance(raw_meta, (dict, list)):
                meta_val = raw_meta
            else:
                s = str(raw_meta)
                if s.strip().startswith("{") or s.strip().startswith("["):
                    meta_val = json.loads(s)
                else:
                    meta_val = {"value": s}
        except Exception:
            meta_val = {}

        history.append({
            "id": str(ev.id),
            "event_type": (et.value if hasattr(et, "value") else str(et)) if et is not None else "",
            "created_at": ev.created_at.isoformat(),
            "meta": meta_val or {},
        })

    return {
        "id": str(u.id),
        "name": u.name,
        "role": u.role.value,
        "position": u.position,
        "xp": int(u.xp or 0),
        "level": int(u.level or 0),
        "streak": int(u.streak or 0),
        "must_change_password": bool(getattr(u, "must_change_password", False)),
        "password_changed_at": u.password_changed_at.isoformat() if getattr(u, "password_changed_at", None) else None,
        "last_activity_at": u.last_activity_at.isoformat() if getattr(u, "last_activity_at", None) else None,
        "created_at": u.created_at.isoformat() if getattr(u, "created_at", None) else None,
        "stats": {
            "assignments_total": int(assignments_total),
            "assignments_completed": int(assignments_completed),
            "attempts_total": int(attempts_total),
            "attempts_passed": int(attempts_passed),
            "events_total": int(events_total),
        },
        "modules_progress": {
            "completed": completed_modules,
            "in_progress": in_progress_modules,
        },
        "history": history,
    }


@router.get("/users/{user_id}/history", response_model=HistoryResponse)
def admin_user_history(
    user_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    limit: int = Query(default=200),
):
    # Same output as /me/history but for any user.
    uid = _uuid(user_id, field="user_id")
    take = max(1, min(int(limit or 200), 500))

    attempts = db.scalars(
        select(QuizAttempt)
        .where(QuizAttempt.user_id == uid)
        .order_by(QuizAttempt.started_at.desc())
        .limit(take)
    ).all()
    events = db.scalars(
        select(LearningEvent)
        .where(LearningEvent.user_id == uid)
        .order_by(LearningEvent.created_at.desc())
        .limit(take)
    ).all()

    sec_events = db.scalars(
        select(SecurityAuditEvent)
        .where(SecurityAuditEvent.target_user_id == uid)
        .where(SecurityAuditEvent.event_type.in_(["auth_login_new_context", "auth_login_success"]))
        .order_by(SecurityAuditEvent.created_at.desc())
        .limit(take)
    ).all()

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

    def _event_display(e: LearningEvent) -> tuple[str, str, str | None]:
        t = e.type.value
        meta = _try_parse_meta(e.meta)
        action = str((meta or {}).get("action") or "").strip().lower() if meta else ""
        if t == "submodule_opened":
            if action == "read" or (e.meta or "").strip().lower() == "read":
                return ("lesson", "Теория подтверждена", "Отмечено как прочитано")
            return ("lesson", "Открыт урок", "Просмотр")
        if t == "asset_viewed":
            fname = str((meta or {}).get("filename") or "").strip() if meta else ""
            if action == "view":
                return ("asset", "Открыл материал", fname or None)
            if action == "download":
                return ("asset", "Скачал материал", fname or None)
            return ("asset", "Материал", fname or None)
        if t == "quiz_started":
            return ("quiz", "Начат тест", None)
        if t == "quiz_completed":
            if meta and meta.get("score") is not None:
                try:
                    score = int(meta.get("score"))
                    passed = bool(meta.get("passed"))
                    return ("quiz", "Завершён тест", f"{score}% · {'зачёт' if passed else 'не зачёт'}")
                except Exception:
                    pass
            return ("quiz", "Завершён тест", None)
        return ("event", "Событие", None)

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
                "subtitle": (f"{int(a.score)}% · {'зачёт' if a.passed else 'не зачёт'}" if a.score is not None else None),
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
                "module_id": ctx.get("module_id"),
                "module_title": ctx.get("module_title"),
                "submodule_id": ctx.get("submodule_id"),
                "submodule_title": ctx.get("submodule_title"),
                "asset_id": None,
                "asset_name": None,
            }
        )

    for e in events:
        kind, title, subtitle = _event_display(e)
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
                "module_id": module_id,
                "module_title": module_title,
                "submodule_id": submodule_id,
                "submodule_title": submodule_title,
                "asset_id": asset_id,
                "asset_name": asset_name,
            }
        )

    for se in sec_events:
        title, subtitle = _sec_event_display(se)
        items.append(
            {
                "id": str(se.id),
                "created_at": se.created_at.isoformat(),
                "kind": "security",
                "title": title,
                "subtitle": subtitle,
                "href": None,
                "event_type": str(se.event_type),
                "ref_id": None,
                "meta": se.meta,
                "module_id": None,
                "module_title": None,
                "submodule_id": None,
                "submodule_title": None,
                "asset_id": None,
                "asset_name": None,
            }
        )

    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return {"items": items[:take]}


@router.delete("/users/{user_id}")
def delete_user(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_delete_user", limit=10, window_seconds=60),
):
    uid = _uuid(user_id, field="user_id")
    if uid == current.id:
        raise HTTPException(status_code=400, detail="cannot delete self")

    u = db.scalar(select(User).where(User.id == uid))
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")

    try:
        attempt_ids = db.scalars(select(QuizAttempt.id).where(QuizAttempt.user_id == uid)).all()
        if attempt_ids:
            db.execute(delete(QuizAttemptAnswer).where(QuizAttemptAnswer.attempt_id.in_(attempt_ids)))
            db.execute(delete(QuizAttempt).where(QuizAttempt.id.in_(attempt_ids)))

        db.execute(delete(LearningEvent).where(LearningEvent.user_id == uid))
        db.execute(delete(UserSkill).where(UserSkill.user_id == uid))

        db.execute(delete(Assignment).where(Assignment.assigned_to == uid))
        db.execute(delete(Assignment).where(Assignment.assigned_by == uid))

        # Keep audit trail shape, but remove hard references to deleted user.
        db.execute(
            text("UPDATE security_audit_events SET actor_user_id = NULL WHERE actor_user_id = :uid"),
            {"uid": uid},
        )
        db.execute(
            text("UPDATE security_audit_events SET target_user_id = NULL WHERE target_user_id = :uid"),
            {"uid": uid},
        )

        db.execute(delete(User).where(User.id == uid))

        audit_log(db=db, request=request, event_type="admin_delete_user", actor_user_id=current.id, target_user_id=uid)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="failed to delete user") from e

    return {"ok": True}


@router.post("/users", response_model=UserCreateResponse)
def create_user(
    request: Request,
    body: UserCreateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_create_user", limit=20, window_seconds=60),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="invalid name")

    existing = db.scalar(select(User).where(User.name == name))
    if existing is not None:
        raise HTTPException(status_code=409, detail="user already exists")

    temp_password = (body.password or "").strip() or _random_password(12)
    if len(temp_password) < int(settings.password_min_length or 0):
        raise HTTPException(status_code=400, detail="password too short")

    user = User(
        name=name,
        position=body.position,
        role=UserRole(str(body.role)),
        xp=0,
        level=1,
        streak=0,
        password_hash=_hash_password(temp_password),
        must_change_password=bool(body.must_change_password),
        password_changed_at=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit_log(db=db, request=request, event_type="admin_create_user", actor_user_id=current.id, target_user_id=user.id)
    db.commit()

    return {"id": str(user.id), "temp_password": temp_password}


@router.post("/users/{user_id}/reset-password", response_model=UserResetPasswordResponse)
def reset_user_password(
    request: Request,
    user_id: str,
    body: UserResetPasswordRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="admin_reset_password", limit=20, window_seconds=60),
):
    uid = _uuid(user_id, field="user_id")
    user = db.scalar(select(User).where(User.id == uid))
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    temp_password = (body.password or "").strip() or _random_password(12)
    if len(temp_password) < int(settings.password_min_length or 0):
        raise HTTPException(status_code=400, detail="password too short")

    user.password_hash = _hash_password(temp_password)
    user.must_change_password = bool(body.must_change_password)
    user.password_changed_at = None
    db.add(user)
    db.commit()

    audit_log(db=db, request=request, event_type="admin_reset_password", actor_user_id=current.id, target_user_id=user.id)
    db.commit()

    return {"ok": True, "temp_password": temp_password}


@router.get("/analytics/modules/{module_id}", response_model=ModuleAnalyticsResponse)
def module_analytics(
    module_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    mid = _uuid(module_id, field="module_id")
    m = db.scalar(select(Module).where(Module.id == mid))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    learning_service = LearningService(db)
    rows = learning_service.get_modules_analytics_batch(mid)

    return {"module_id": str(m.id), "module_title": m.title, "rows": rows}


@router.get("/analytics/modules/{module_id}/question-quality")
def module_question_quality(
    module_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    mid = _uuid(module_id, field="module_id")
    m = db.scalar(select(Module).where(Module.id == mid))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    # Collect all quiz ids participating in the module (submodules + final)
    quiz_ids = [
        qid
        for (qid,) in db.execute(select(Submodule.quiz_id).where(Submodule.module_id == mid)).all()
        if qid is not None
    ]
    if m.final_quiz_id:
        quiz_ids.append(m.final_quiz_id)

    quiz_ids = list(dict.fromkeys(quiz_ids))
    if not quiz_ids:
        return {"module_id": str(m.id), "module_title": m.title, "items": []}

    take = max(1, min(int(limit or 50), 200))

    incorrect_sum = func.sum(case((QuizAttemptAnswer.is_correct == False, 1), else_=0)).label("incorrect")
    total_cnt = func.count(QuizAttemptAnswer.id).label("total")

    rows = (
        db.execute(
            select(
                Question.id.label("question_id"),
                Question.prompt.label("prompt"),
                Question.type.label("type"),
                Question.concept_tag.label("concept_tag"),
                Quiz.id.label("quiz_id"),
                Quiz.type.label("quiz_type"),
                total_cnt,
                incorrect_sum,
            )
            .select_from(QuizAttemptAnswer)
            .join(QuizAttempt, QuizAttempt.id == QuizAttemptAnswer.attempt_id)
            .join(Question, Question.id == QuizAttemptAnswer.question_id)
            .join(Quiz, Quiz.id == Question.quiz_id)
            .where(QuizAttempt.quiz_id.in_(quiz_ids))
            .where(Question.quiz_id.in_(quiz_ids))
            .group_by(Question.id, Question.prompt, Question.type, Question.concept_tag, Quiz.id, Quiz.type)
        )
        .all()
    )

    items: list[dict[str, object]] = []
    for r in rows:
        total = int(getattr(r, "total") or 0)
        incorrect = int(getattr(r, "incorrect") or 0)
        failure_rate = float(incorrect) / float(total) if total > 0 else 0.0
        items.append(
            {
                "question_id": str(getattr(r, "question_id")),
                "quiz_id": str(getattr(r, "quiz_id")),
                "quiz_type": getattr(getattr(r, "quiz_type"), "value", str(getattr(r, "quiz_type"))),
                "type": getattr(getattr(r, "type"), "value", str(getattr(r, "type"))),
                "concept_tag": getattr(r, "concept_tag"),
                "prompt": getattr(r, "prompt") or "",
                "total": total,
                "incorrect": incorrect,
                "failure_rate": round(failure_rate, 4),
            }
        )

    items.sort(key=lambda x: (float(x.get("failure_rate") or 0.0), int(x.get("total") or 0)), reverse=True)
    items = items[:take]

    return {"module_id": str(m.id), "module_title": m.title, "items": items}


@router.get("/quizzes/{quiz_id}/answer-key")
def quiz_answer_key(
    request: Request,
    quiz_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_roles(UserRole.admin)),
):
    qid = _uuid(quiz_id, field="quiz_id")
    quiz = db.scalar(select(Quiz).where(Quiz.id == qid))
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz not found")

    questions = db.scalars(select(Question).where(Question.quiz_id == quiz.id)).all()
    audit_log(
        db=db,
        request=request,
        event_type="admin_view_quiz_answer_key",
        actor_user_id=current.id,
        meta={"quiz_id": str(quiz.id), "question_count": len(questions)},
    )
    db.commit()
    return {
        "quiz_id": str(quiz.id),
        "type": getattr(quiz.type, "value", str(quiz.type)),
        "pass_threshold": int(quiz.pass_threshold or 0),
        "questions": [
            {
                "id": str(q.id),
                "type": getattr(q.type, "value", str(q.type)),
                "prompt": q.prompt,
                "correct_answer": q.correct_answer,
                "concept_tag": q.concept_tag,
            }
            for q in questions
        ],
    }
