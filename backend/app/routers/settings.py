"""Administrator-editable settings: AI drafts, Google Sheets and S3 storage.

Secrets are encrypted before storage (database) or masked (storage override)
and are never returned in clear text. Every change is audited; saving does not
require a restart because the API and RQ workers resolve the effective value on
each use: database first, then the storage override, then the environment.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.core.security import require_roles
from app.core.security_audit_log import audit_log
from app.db.session import get_db
from app.models.user import User, UserRole
from app.services.app_settings import (ai_settings_payload, get_ai_settings, get_platform_settings,
    get_sales_settings, get_storage_settings, platform_settings_payload, reset_ai_settings,
    reset_platform_settings, reset_sales_settings, reset_storage_settings, save_ai_settings,
    save_platform_settings, save_sales_settings, save_storage_settings, sales_settings_payload,
    SettingsValidationError, storage_settings_payload)
from app.services.google_sheets import list_sheet_titles
from app.services.openrouter_health import list_ai_models, probe_ai_connection

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])

_SCHEMA_REVISION: str | None = None
_SCHEMA_REVISION_FALLBACK = "0024"


def expected_schema_revision() -> str:
    """Alembic head, so the settings screen cannot drift from the migrations."""
    global _SCHEMA_REVISION
    if _SCHEMA_REVISION:
        return _SCHEMA_REVISION
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        head = ScriptDirectory.from_config(config).get_current_head()
        if head:
            _SCHEMA_REVISION = str(head)
            return _SCHEMA_REVISION
    except Exception:
        log.debug("settings: could not read the alembic head", exc_info=True)
    return _SCHEMA_REVISION_FALLBACK


def _storage_effective(kind: str) -> str:
    try:
        from app.services import storage

        return str(getattr(storage, f"effective_{kind}")() or "")
    except Exception:
        return ""


class AISettingsSave(BaseModel):
    enabled: bool = True
    api_key: str | None = None
    clear_api_key: bool = False
    base_url: str = ""
    model: str = ""
    http_referer: str = ""
    app_title: str = ""


class AITestRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class AIModelsRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None


class SalesSettingsSave(BaseModel):
    spreadsheet_id: str = ""
    service_account_json: str | None = None
    api_key: str | None = None
    clear_service_account: bool = False
    clear_api_key: bool = False


class SalesTestRequest(BaseModel):
    spreadsheet_id: str | None = None
    service_account_json: str | None = None
    api_key: str | None = None
    use_saved: bool = True


def _ok(payload: dict) -> dict:
    return {"ok": True, **payload}


@router.get("/ai")
def read_ai_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    return ai_settings_payload(get_ai_settings(db))


@router.put("/ai")
def write_ai_settings(
    request: Request,
    body: AISettingsSave,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
    __: object = rate_limit(key_prefix="admin_ai_settings", limit=30, window_seconds=60),
):
    try:
        save_ai_settings(
            db,
            actor_id=user.id,
            enabled=body.enabled,
            api_key=body.api_key,
            clear_api_key=body.clear_api_key,
            base_url=body.base_url,
            model=body.model,
            http_referer=body.http_referer,
            app_title=body.app_title,
        )
    except SettingsValidationError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    config = get_ai_settings(db)
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="admin_ai_settings_saved",
              meta={"enabled": config.enabled, "configured": config.configured,
                    "token_source": config.sources.get("api_key"), "model": config.model,
                    "base_url": config.base_url})
    db.commit()
    return _ok({"settings": ai_settings_payload(config), "restart_required": False})


@router.delete("/ai")
def clear_ai_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
):
    reset_ai_settings(db)
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="admin_ai_settings_reset", meta={})
    db.commit()
    return _ok({"settings": ai_settings_payload(get_ai_settings(db))})


@router.post("/ai/models")
def list_ai_settings_models(
    body: AIModelsRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    __: object = rate_limit(key_prefix="admin_ai_models", limit=20, window_seconds=60),
):
    """Catalogue of models the configured gateway really offers.

    The saved token is used when the field is empty, so the operator can pick a
    working model before saving anything. A rejected token is reported instead of
    being echoed back.
    """
    saved = get_ai_settings(db)
    token = str(body.api_key or "").strip() or saved.api_key
    base_url = str(body.base_url or "").strip() or saved.base_url
    if not base_url:
        raise HTTPException(422, "Укажите адрес API (например, https://openrouter.ai/api/v1)")
    result = list_ai_models(api_key=token, base_url=base_url)
    return {**result.as_dict(), "using_saved_token": not bool(str(body.api_key or "").strip()),
            "base_url": base_url}


@router.post("/ai/test")
def test_ai_settings(
    body: AITestRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    __: object = rate_limit(key_prefix="admin_ai_settings_test", limit=10, window_seconds=60),
):
    saved = get_ai_settings(db)
    token = str(body.api_key or "").strip() or saved.api_key
    base_url = str(body.base_url or "").strip() or saved.base_url
    model = str(body.model or "").strip() or saved.model
    if not token:
        raise HTTPException(422, "Сначала введите API-токен")
    if not base_url:
        raise HTTPException(422, "Укажите адрес API (например, https://openrouter.ai/api/v1)")
    result = probe_ai_connection(api_key=token, base_url=base_url, model=model or None)
    return {**result.as_dict(), "using_saved_token": not bool(str(body.api_key or "").strip()),
            "model": model or None, "base_url": base_url}


@router.get("/sales")
def read_sales_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.superadmin)),
):
    return sales_settings_payload(get_sales_settings(db))


@router.put("/sales")
def write_sales_settings(
    request: Request,
    body: SalesSettingsSave,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.superadmin)),
    __: object = rate_limit(key_prefix="admin_sales_settings", limit=20, window_seconds=60),
):
    try:
        save_sales_settings(
            db,
            actor_id=user.id,
            spreadsheet_id=body.spreadsheet_id,
            service_account_json=body.service_account_json,
            api_key=body.api_key,
            clear_service_account=body.clear_service_account,
            clear_api_key=body.clear_api_key,
        )
    except SettingsValidationError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    config = get_sales_settings(db)
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="admin_sales_settings_saved",
              meta={"configured": config.configured, "spreadsheet_id": config.spreadsheet_id,
                    "credentials": "service_account" if config.service_account_json else "api_key" if config.api_key else "none"})
    db.commit()
    return _ok({"settings": sales_settings_payload(config), "restart_required": False})


@router.delete("/sales")
def clear_sales_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.superadmin)),
):
    reset_sales_settings(db)
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="admin_sales_settings_reset", meta={})
    db.commit()
    return _ok({"settings": sales_settings_payload(get_sales_settings(db))})


@router.post("/sales/test")
def test_sales_settings(
    body: SalesTestRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.superadmin)),
    __: object = rate_limit(key_prefix="admin_sales_settings_test", limit=10, window_seconds=60),
):
    saved = get_sales_settings(db)
    spreadsheet_id = str(body.spreadsheet_id or "").strip() or (saved.spreadsheet_id if body.use_saved else "")
    creds = str(body.service_account_json or "").strip() or (saved.service_account_json if body.use_saved else "")
    api_key = str(body.api_key or "").strip() or (saved.api_key if body.use_saved else "")
    if not spreadsheet_id:
        raise HTTPException(422, "Укажите идентификатор таблицы")
    if not creds and not api_key:
        raise HTTPException(422, "Добавьте ключ сервисного аккаунта или Google API key")
    service_email = saved.service_account_email
    if creds:
        try:
            service_email = str(json.loads(creds).get("client_email") or "").strip() or service_email
        except (TypeError, ValueError):
            service_email = saved.service_account_email
    try:
        titles = list_sheet_titles(spreadsheet_id=spreadsheet_id, creds_json=creds or None, api_key=api_key or None)
    except Exception as exc:  # googleapiclient exposes status in HttpError
        status = None
        try:
            status = int(getattr(getattr(exc, "resp", None), "status", None) or 0) or None
        except Exception:
            status = None
        if status == 403:
            message = "Нет доступа к таблице. Откройте её для адреса сервисного аккаунта с правом «Читатель»."
        elif status == 404:
            message = "Таблица не найдена. Проверьте идентификатор и доступ сервисного аккаунта."
        elif status == 400:
            message = "Google отклонил запрос. Проверьте ключ и идентификатор таблицы."
        else:
            message = "Не удалось прочитать таблицу. Проверьте ключ, доступ к таблице и сеть."
        return {"ok": False, "status": status, "message": message,
                "service_account_email": service_email}
    return {"ok": True, "status": 200, "sheets": titles, "count": len(titles),
            "message": f"Таблица доступна. Листов: {len(titles)}.",
            "service_account_email": service_email}


@router.get("/overview")
def settings_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    schema_revision = None
    try:
        schema_revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        db.rollback()
    schema_expected = expected_schema_revision()
    workers = None
    regen_queue = None
    try:
        import redis as redis_lib
        from rq import Queue
        from rq.worker import Worker
        conn = redis_lib.Redis.from_url(str(getattr(settings, "redis_url", "") or ""))
        workers = int(len(Worker.all(connection=conn)))
        regen_queue = int(Queue(str(getattr(settings, "rq_queue_regen", "") or ""), connection=conn).count)
    except Exception:
        workers = None
    platform = get_platform_settings(db)
    return {
        "app_env": str(getattr(settings, "app_env", "") or ""),
        "public_app_url": str(getattr(settings, "public_app_url", "") or ""),
        "cors_allow_origins": str(getattr(settings, "cors_allow_origins", "") or ""),
        "upload_max_bytes": int(platform.upload_max_bytes or 0),
        "allow_public_register": bool(platform.allow_public_register),
        "s3_bucket": _storage_effective("bucket"),
        "s3_endpoint": _storage_effective("endpoint"),
        "media_dispatcher_enabled": bool(getattr(settings, "media_dispatcher_enabled", False)),
        "schema": {"current": schema_revision, "expected": schema_expected,
                   "up_to_date": schema_revision == schema_expected},
        "queue": {"media": str(getattr(settings, "rq_queue_media", "") or ""),
                  "regen": str(getattr(settings, "rq_queue_regen", "") or ""),
                  "workers": workers, "regen_pending": regen_queue},
    }


# --- Storage (S3) -----------------------------------------------------------
# Stored with the other integrations: encrypted in the database, resolved on
# every S3 call, so saving needs no restart and survives Redis restarts.

class StorageSettingsSave(BaseModel):
    s3_endpoint_url: str = ""
    s3_public_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_region_name: str = ""
    s3_addressing_style: str = ""
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    clear_credentials: bool = False


class PlatformSettingsSave(BaseModel):
    upload_max_bytes: int
    allow_public_register: bool = False


def _storage_payload(db: Session) -> dict:
    from app.services.storage import effective_bucket, effective_endpoint, effective_public_endpoint

    payload = storage_settings_payload(get_storage_settings(db))
    payload.update({
        "editable": True,
        "effective": {
            "bucket": effective_bucket(),
            "endpoint": effective_endpoint(),
            "public_endpoint": effective_public_endpoint(),
        },
        # Kept for the settings screen: the fields it may pre-fill.
        "overrides": {
            "s3_endpoint_url": payload["fields"]["s3_endpoint_url"],
            "s3_public_endpoint_url": payload["fields"]["s3_public_endpoint_url"],
            "s3_bucket": payload["fields"]["s3_bucket"],
            "s3_region_name": payload["fields"]["s3_region_name"],
            "s3_addressing_style": payload["fields"]["s3_addressing_style"],
        },
    })
    return payload


@router.get("/storage")
def read_storage_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    return _storage_payload(db)


@router.put("/storage")
def write_storage_settings(
    request: Request,
    body: StorageSettingsSave,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
    __: object = rate_limit(key_prefix="admin_storage_settings", limit=20, window_seconds=60),
):
    try:
        save_storage_settings(
            db,
            actor_id=user.id,
            endpoint_url=body.s3_endpoint_url,
            public_endpoint_url=body.s3_public_endpoint_url,
            bucket=body.s3_bucket,
            region_name=body.s3_region_name,
            addressing_style=body.s3_addressing_style,
            access_key_id=body.s3_access_key_id,
            secret_access_key=body.s3_secret_access_key,
            clear_credentials=body.clear_credentials,
        )
    except SettingsValidationError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    config = get_storage_settings(db)
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="admin_storage_settings_saved",
              meta={"bucket": config.bucket, "endpoint": config.endpoint_url,
                    "credentials_changed": bool(body.s3_access_key_id or body.s3_secret_access_key
                                                or body.clear_credentials)})
    db.commit()
    return _ok({"settings": _storage_payload(db), "restart_required": False})


@router.delete("/storage")
def clear_storage_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
):
    reset_storage_settings(db)
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="admin_storage_settings_reset", meta={})
    db.commit()
    return _ok({"settings": _storage_payload(db)})


@router.post("/storage/test")
def test_storage_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
    __: object = rate_limit(key_prefix="admin_storage_settings_test", limit=10, window_seconds=60),
):
    from app.services.storage import effective_bucket, effective_endpoint, get_s3_client

    bucket = effective_bucket()
    endpoint = effective_endpoint()
    if not bucket:
        return {"ok": False, "bucket": "", "endpoint": endpoint, "message": "Укажите имя bucket и сохраните настройки."}
    try:
        get_s3_client().head_bucket(Bucket=bucket)
    except Exception as exc:
        detail = str(exc or "").splitlines()[0][:200]
        return {"ok": False, "bucket": bucket, "endpoint": endpoint,
                "message": "Хранилище недоступно. Проверьте адрес, ключи и имя bucket."
                           + (f" Ответ: {detail}" if detail else "")}
    return {"ok": True, "bucket": bucket, "endpoint": endpoint,
            "message": f"Bucket «{bucket}» доступен, ключи приняты."}


# --- Platform limits --------------------------------------------------------


@router.get("/platform")
def read_platform_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    return platform_settings_payload(get_platform_settings(db))


@router.put("/platform")
def write_platform_settings(
    request: Request,
    body: PlatformSettingsSave,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
    __: object = rate_limit(key_prefix="admin_platform_settings", limit=20, window_seconds=60),
):
    try:
        save_platform_settings(db, actor_id=user.id, upload_max_bytes=body.upload_max_bytes,
                               allow_public_register=body.allow_public_register)
    except SettingsValidationError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    config = get_platform_settings(db)
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="admin_platform_settings_saved",
              meta={"upload_max_bytes": config.upload_max_bytes,
                    "allow_public_register": config.allow_public_register})
    db.commit()
    return _ok({"settings": platform_settings_payload(config), "restart_required": False})


@router.delete("/platform")
def clear_platform_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.admin)),
):
    reset_platform_settings(db)
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="admin_platform_settings_reset", meta={})
    db.commit()
    return _ok({"settings": platform_settings_payload(get_platform_settings(db))})
