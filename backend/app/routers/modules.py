from __future__ import annotations

import asyncio
import json
import threading
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis
from app.core.security import get_current_user
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models.asset import ContentAsset
from app.models.audit import LearningEvent, LearningEventType
from app.models.module import Module, Submodule
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.user import User
from app.schemas.modules_overview import ModulesOverviewResponse
from app.schemas.module import ModulePublic, SubmoduleAssetsResponse, SubmodulePublic
from app.services.modules import ModuleService
from app.services.skills import record_activity_and_award_xp

router = APIRouter(prefix="/modules", tags=["modules"])


def _modules_get_rev() -> int:
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


@router.get("/overview", response_model=ModulesOverviewResponse)
def modules_overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service = ModuleService(db)
    items = service.get_modules_overview(user)
    return {"items": items}


@router.get("", response_model=list[ModulePublic])
def list_modules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service = ModuleService(db)
    modules = service._get_accessible_modules(user)
    return [
        {
            "id": str(m.id),
            "title": m.title,
            "description": m.description,
            "difficulty": m.difficulty,
            "category": m.category,
            "is_active": m.is_active,
        }
        for m in modules
    ]


@router.get("/events")
async def modules_events(request: Request, _: User = Depends(get_current_user)):
    async def gen():
        loop = asyncio.get_running_loop()
        q: asyncio.Queue[object] = asyncio.Queue()
        stop = threading.Event()
        pubsub_ref: dict[str, object] = {}

        def _push(msg: object) -> None:
            try:
                loop.call_soon_threadsafe(q.put_nowait, msg)
            except Exception:
                pass

        def _listen() -> None:
            pubsub = None
            try:
                r = get_redis()
                pubsub = r.pubsub(ignore_subscribe_messages=True)
                pubsub_ref["pubsub"] = pubsub
                pubsub.subscribe("modules:changed")
                while not stop.is_set():
                    try:
                        m = pubsub.get_message(timeout=1.0)
                    except Exception:
                        m = None
                    if m:
                        _push(m)
            except Exception:
                while not stop.is_set():
                    stop.wait(2.0)
                    _push({"type": "tick"})
            finally:
                try:
                    ps = pubsub if pubsub is not None else pubsub_ref.get("pubsub")
                    if ps is not None:
                        try:
                            ps.unsubscribe("modules:changed")
                        except Exception:
                            pass
                        try:
                            ps.close()
                        except Exception:
                            pass
                except Exception:
                    pass

        t = threading.Thread(target=_listen, name="modules_sse_pubsub", daemon=True)
        t.start()

        last_rev = 0
        last_ping_ms = 0
        last_sent_sig = ""

        try:
            _push({"type": "init"})
        except Exception:
            pass

        try:
            while True:
                try:
                    if await request.is_disconnected():
                        break
                except Exception:
                    pass

                now_ms = int(datetime.utcnow().timestamp() * 1000)
                timeout_s = max(0.25, (15000 - (now_ms - last_ping_ms)) / 1000.0) if last_ping_ms else 2.0

                msg = None
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=timeout_s)
                except asyncio.TimeoutError:
                    msg = None
                except Exception:
                    msg = None

                # Authoritative: always read current rev from Redis.
                try:
                    rev = _modules_get_rev()
                except Exception:
                    rev = 0

                if rev and rev > last_rev:
                    last_rev = rev
                    payload = {"rev": int(rev), "ts": datetime.utcnow().isoformat()}
                    sig = ""
                    try:
                        sig = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                    except Exception:
                        sig = str(payload.get("ts") or "")
                    if sig and sig != last_sent_sig:
                        last_sent_sig = sig
                        data = json.dumps(payload, ensure_ascii=False)
                        yield f"event: modules\ndata: {data}\n\n"

                now_ms = int(datetime.utcnow().timestamp() * 1000)
                if (not last_ping_ms) or (now_ms - last_ping_ms >= 15000):
                    last_ping_ms = now_ms
                    yield ": ping\n\n"
        finally:
            stop.set()
            try:
                _push({"type": "stop"})
            except Exception:
                pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{module_id}", response_model=ModulePublic)
def get_module(module_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    m = db.scalar(select(Module).where(Module.id == module_id))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    return {
        "id": str(m.id),
        "title": m.title,
        "description": m.description,
        "difficulty": m.difficulty,
        "category": m.category,
        "is_active": m.is_active,
    }


@router.post("/{module_id}/open")
def open_module(
    module_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: object = rate_limit(key_prefix="module_open", limit=120, window_seconds=60),
):
    m = db.scalar(select(Module).where(Module.id == module_id))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    # Count module open as activity for streak, but do not award XP.
    record_activity_and_award_xp(db, user_id=str(user.id), xp=0)

    # Note: do NOT introduce a new LearningEventType (would require DB enum migration).
    # Reuse submodule_opened with ref_id=None and encode action in meta.
    try:
        meta = json.dumps({"action": "module_open", "module_id": str(m.id)}, ensure_ascii=False)
    except Exception:
        meta = "module_open"

    db.add(
        LearningEvent(
            user_id=user.id,
            type=LearningEventType.submodule_opened,
            ref_id=None,
            meta=meta,
        )
    )
    db.commit()
    return {"ok": True}


@router.get("/{module_id}/submodules", response_model=list[SubmodulePublic])
def list_submodules(module_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(Submodule).where(Submodule.module_id == module_id).order_by(Submodule.order)).all()
    return [
        {
            "id": str(s.id),
            "module_id": str(s.module_id),
            "title": s.title,
            "order": s.order,
            "quiz_id": str(s.quiz_id),
            "requires_quiz": bool(getattr(s, "requires_quiz", True)),
            "is_folder": bool(getattr(s, "is_folder", False)),
            "outline_path": str(getattr(s, "outline_path", None)) if getattr(s, "outline_path", None) else None,
        }
        for s in rows
    ]


@router.get("/submodules/{submodule_id}/assets", response_model=SubmoduleAssetsResponse)
def submodule_assets(submodule_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    sub = db.scalar(select(Submodule).where(Submodule.id == submodule_id))
    if sub is None:
        raise HTTPException(status_code=404, detail="submodule not found")

    stmt = (
        select(SubmoduleAssetMap.order, ContentAsset)
        .join(ContentAsset, ContentAsset.id == SubmoduleAssetMap.asset_id)
        .where(SubmoduleAssetMap.submodule_id == sub.id)
        .order_by(SubmoduleAssetMap.order)
    )
    rows = db.execute(stmt).all()

    return {
        "submodule_id": str(sub.id),
        "assets": [
            {
                "asset_id": str(asset.id),
                "object_key": asset.object_key,
                "original_filename": asset.original_filename,
                "mime_type": asset.mime_type,
                "size_bytes": asset.size_bytes,
                "order": int(order),
            }
            for order, asset in rows
        ],
    }


@router.get("/{module_id}/assets")
def module_assets(module_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    m = db.scalar(select(Module).where(Module.id == module_id))
    if m is None:
        raise HTTPException(status_code=404, detail="module not found")

    # Convention (no DB migrations): module-level materials are stored by object_key prefix.
    # IMPORTANT: lesson files are linked via SubmoduleAssetMap, so do NOT list them here.
    pfx = str(getattr(m, "storage_prefix", "") or "").strip() or f"modules/{module_id}/"
    if pfx and (not pfx.endswith("/")):
        pfx = pfx + "/"
    prefix = f"{pfx}_module/"
    assets = db.scalars(
        select(ContentAsset).where(ContentAsset.object_key.like(prefix + "%")).order_by(ContentAsset.original_filename)
    ).all()

    return {
        "module_id": str(m.id),
        "assets": [
            {
                "asset_id": str(a.id),
                "object_key": a.object_key,
                "original_filename": a.original_filename,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
            }
            for a in assets
        ],
    }
