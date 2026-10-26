"""Runtime application settings that administrators can edit in the LMS.

Precedence is deliberately explicit:

1. values saved here (database, secrets encrypted at rest);
2. legacy ``runtime:llm`` Redis overrides, when runtime overrides are enabled;
3. process environment (``OPENROUTER_*``, ``SALES_LINKS_*``).

Resolution always happens in the process that needs the value, so RQ workers
see a token saved in the UI without a restart. No plaintext secret is ever
returned by the API.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis_client import get_redis
from app.core.secrets import SecretDecryptError, decrypt_secret, encrypt_secret
from app.db.session import SessionLocal
from app.models.app_setting import AppSetting

log = logging.getLogger(__name__)

AI_KEY = "ai"
SALES_KEY = "sales"


class SettingsValidationError(ValueError):
    """A submitted setting is invalid; routers translate it to HTTP 422."""


@dataclass(frozen=True)
class AISettings:
    enabled: bool
    api_key: str
    base_url: str
    model: str
    http_referer: str
    app_title: str
    sources: dict[str, str]
    stored: bool
    updated_at: str | None
    token_error: bool

    @property
    def token_present(self) -> bool:
        return bool(self.api_key)

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.api_key)


@dataclass(frozen=True)
class SalesSettings:
    spreadsheet_id: str
    service_account_json: str
    api_key: str
    sources: dict[str, str]
    stored: bool
    updated_at: str | None
    credentials_error: str | None = None
    service_account_email: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.spreadsheet_id and (self.service_account_json or self.api_key))


@dataclass
class _RawSetting:
    value: dict = field(default_factory=dict)
    updated_at: str | None = None
    exists: bool = False


def mask_secret(value: str | None, *, keep: int = 4) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    if len(raw) <= keep * 2:
        return "•" * 8
    return raw[:keep] + "…" + raw[-keep:]


def _session(db: Session | None):
    return db if db is not None else SessionLocal()


def _read(db: Session | None, key: str) -> _RawSetting:
    session = _session(db)
    owns = db is None
    try:
        row = session.get(AppSetting, key)
        if row is None:
            return _RawSetting()
        try:
            value = json.loads(row.value or "{}")
        except (TypeError, ValueError):
            log.warning("app_settings: invalid JSON for %s", key)
            value = {}
        if not isinstance(value, dict):
            value = {}
        return _RawSetting(value=value, updated_at=row.updated_at.isoformat() if row.updated_at else None, exists=True)
    except SQLAlchemyError:
        # A deploy that has not run migration 0024 yet must still serve content
        # from environment variables instead of returning 500 for every editor.
        log.warning("app_settings: table is unavailable; falling back to environment", exc_info=True)
        try:
            session.rollback()
        except Exception:
            pass
        return _RawSetting()
    finally:
        if owns:
            session.close()


def _write(db: Session, key: str, value: dict, *, actor_id) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value="{}")
        db.add(row)
    row.value = json.dumps(value, ensure_ascii=False)
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = actor_id
    # Request sessions run with autoflush=False; make the new value visible to
    # the immediate read-back without waiting for the router's commit.
    db.flush()


def delete_setting(db: Session, key: str) -> None:
    row = db.get(AppSetting, key)
    if row is not None:
        db.delete(row)
        db.flush()


def _text(value: object) -> str:
    return str(value or "").strip()


def _bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    raw = _text(value).lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return None


def _legacy_runtime_llm() -> dict[str, str]:
    env = _text(getattr(settings, "app_env", "")).lower()
    if env in {"prod", "production"} and not bool(getattr(settings, "allow_runtime_llm_overrides", False)):
        return {}
    try:
        raw = get_redis().hgetall("runtime:llm") or {}
    except Exception:
        log.debug("app_settings: legacy runtime:llm is unavailable", exc_info=True)
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        k = key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else str(key)
        v = value.decode("utf-8", errors="ignore") if isinstance(value, (bytes, bytearray)) else str(value)
        out[k] = v.strip()
    return out


def _pick(name: str, db_value: object, runtime_value: object, env_value: object, sources: dict[str, str]) -> object:
    if db_value not in (None, ""):
        sources[name] = "database"
        return db_value
    if runtime_value not in (None, ""):
        sources[name] = "runtime"
        return runtime_value
    if env_value not in (None, ""):
        sources[name] = "environment"
        return env_value
    sources[name] = "none"
    return None


def stored_ai_values(db: Session | None = None) -> dict:
    """Values explicitly saved by an administrator (no environment fallback)."""
    row = _read(db, AI_KEY)
    raw = row.value
    return {
        "enabled": _bool(raw.get("enabled")),
        "base_url": _text(raw.get("base_url")),
        "model": _text(raw.get("model")),
        "http_referer": _text(raw.get("http_referer")),
        "app_title": _text(raw.get("app_title")),
        "api_key_present": bool(_text(raw.get("api_key"))),
        "updated_at": row.updated_at,
    }


def get_ai_settings(db: Session | None = None) -> AISettings:
    raw = _read(db, AI_KEY)
    value = raw.value
    runtime = _legacy_runtime_llm()
    sources: dict[str, str] = {}

    token_error = False
    db_token = ""
    if _text(value.get("api_key")):
        try:
            db_token = decrypt_secret(value.get("api_key"))
        except SecretDecryptError:
            token_error = True

    runtime_token = _text(runtime.get("openrouter_api_key"))
    env_token = _text(getattr(settings, "openrouter_api_key", ""))
    token = db_token or runtime_token or env_token
    if db_token:
        sources["api_key"] = "database"
    elif runtime_token:
        sources["api_key"] = "runtime"
    elif env_token:
        sources["api_key"] = "environment"
    elif token_error:
        sources["api_key"] = "unreadable"
    else:
        sources["api_key"] = "none"

    db_enabled = _bool(value.get("enabled"))
    runtime_enabled = _bool(runtime.get("openrouter_enabled"))
    env_enabled = bool(getattr(settings, "openrouter_enabled", False)) or bool(env_token)
    if db_enabled is not None:
        enabled, sources["enabled"] = db_enabled, "database"
    elif db_token:
        # A token saved without an explicit flag (legacy import, manual SQL)
        # means the administrator wants drafts to work.
        enabled, sources["enabled"] = True, "database"
    elif runtime_enabled is not None:
        enabled, sources["enabled"] = runtime_enabled, "runtime"
    else:
        enabled, sources["enabled"] = env_enabled, "environment"

    base_url = str(_pick("base_url", _text(value.get("base_url")), _text(runtime.get("openrouter_base_url")),
                         _text(getattr(settings, "openrouter_base_url", "")), sources) or "")
    model = str(_pick("model", _text(value.get("model")), _text(runtime.get("openrouter_model")),
                      _text(getattr(settings, "openrouter_model", "")), sources) or "")
    referer = str(_pick("http_referer", _text(value.get("http_referer")), _text(runtime.get("openrouter_http_referer")),
                        _text(getattr(settings, "openrouter_http_referer", "")), sources) or "")
    app_title = str(_pick("app_title", _text(value.get("app_title")), _text(runtime.get("openrouter_app_title")),
                          _text(getattr(settings, "openrouter_app_title", "")), sources) or "")

    return AISettings(
        enabled=bool(enabled),
        api_key=token,
        base_url=base_url.rstrip("/"),
        model=model,
        http_referer=referer,
        app_title=app_title,
        sources=sources,
        stored=raw.exists,
        updated_at=raw.updated_at,
        # A saved-but-unreadable token is only a problem when no fallback token exists.
        token_error=bool(token_error and not token),
    )


def _validate_http_url(value: str, *, field: str, allow_empty: bool = True) -> str:
    raw = _text(value)
    if not raw:
        if allow_empty:
            return ""
        raise SettingsValidationError(f"{field} обязателен")
    if len(raw) > 500:
        raise SettingsValidationError(f"{field} слишком длинный")
    try:
        parts = urlsplit(raw)
        _ = parts.port
    except ValueError as exc:
        raise SettingsValidationError(f"{field}: некорректный URL") from exc
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise SettingsValidationError(f"{field}: разрешены только http(s) URL без логина и пароля")
    return raw.rstrip("/")


def save_ai_settings(
    db: Session,
    *,
    actor_id,
    enabled: bool,
    api_key: str | None = None,
    clear_api_key: bool = False,
    base_url: str = "",
    model: str = "",
    http_referer: str = "",
    app_title: str = "",
) -> AISettings:
    current = _read(db, AI_KEY)
    value = dict(current.value)
    value["enabled"] = bool(enabled)
    for key, raw in (("base_url", base_url), ("model", model), ("http_referer", http_referer), ("app_title", app_title)):
        cleaned = _text(raw)
        if len(cleaned) > (300 if key == "model" else 500 if key == "base_url" else 200):
            raise SettingsValidationError("Слишком длинное значение настройки")
        if cleaned:
            value[key] = cleaned
        else:
            value.pop(key, None)
    value["base_url"] = _validate_http_url(str(value.get("base_url") or ""), field="Адрес API")
    if value.get("http_referer"):
        value["http_referer"] = _validate_http_url(str(value["http_referer"]), field="HTTP-Referer")

    if clear_api_key:
        value.pop("api_key", None)
    elif api_key is not None and str(api_key).strip():
        raw = str(api_key).strip()
        if len(raw) > 4000:
            raise SettingsValidationError("Токен слишком длинный")
        if any(ch.isspace() for ch in raw):
            raise SettingsValidationError("Токен не должен содержать пробелы")
        value["api_key"] = encrypt_secret(raw)
    if not value.get("base_url"):
        value.pop("base_url", None)
    _write(db, AI_KEY, value, actor_id=actor_id)
    # A token saved in the UI must win over a stale legacy Redis value.
    try:
        get_redis().delete("runtime:llm")
    except Exception:
        log.debug("app_settings: could not clear legacy runtime:llm", exc_info=True)
    return get_ai_settings(db)


def reset_ai_settings(db: Session) -> None:
    delete_setting(db, AI_KEY)
    try:
        get_redis().delete("runtime:llm")
    except Exception:
        log.debug("app_settings: could not clear legacy runtime:llm", exc_info=True)


def _parse_service_account(raw: str) -> dict:
    if not _text(raw):
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise SettingsValidationError("JSON сервисного аккаунта не разобран. Скопируйте файл целиком.") from exc
    if not isinstance(data, dict) or not _text(data.get("client_email")) or not _text(data.get("private_key")):
        raise SettingsValidationError("В JSON нужны поля client_email и private_key сервисного аккаунта")
    return data


def get_sales_settings(db: Session | None = None) -> SalesSettings:
    raw = _read(db, SALES_KEY)
    value = raw.value
    sources: dict[str, str] = {}
    credentials_error = None
    service_email = None
    db_creds = ""
    if _text(value.get("service_account_json")):
        try:
            db_creds = decrypt_secret(value.get("service_account_json"))
        except SecretDecryptError:
            credentials_error = "Сохранённый ключ сервисного аккаунта не читается. Введите его заново."
    elif _text(value.get("credentials")):
        # Plain legacy/manual value: keep it usable, but new saves are encrypted.
        db_creds = _text(value.get("credentials"))
    db_api_key = ""
    if _text(value.get("api_key")):
        try:
            db_api_key = decrypt_secret(value.get("api_key"))
        except SecretDecryptError:
            credentials_error = credentials_error or "Сохранённый Google API key не читается. Введите его заново."

    env_creds = _text(getattr(settings, "sales_links_service_account_json", ""))
    env_api_key = _text(getattr(settings, "sales_links_google_api_key", ""))
    spreadsheet_id = str(_pick("spreadsheet_id", _text(value.get("spreadsheet_id")), "",
                               _text(getattr(settings, "sales_links_spreadsheet_id", "")), sources) or "")
    service_account_json = str(_pick("service_account_json", db_creds, "", env_creds, sources) or "")
    api_key = str(_pick("api_key", db_api_key, "", env_api_key, sources) or "")
    if service_account_json:
        try:
            service_email = _text(json.loads(service_account_json).get("client_email")) or None
        except (TypeError, ValueError):
            service_email = None
    return SalesSettings(
        spreadsheet_id=spreadsheet_id,
        service_account_json=service_account_json,
        api_key=api_key,
        sources=sources,
        stored=raw.exists,
        updated_at=raw.updated_at,
        credentials_error=credentials_error,
        service_account_email=service_email,
    )


def save_sales_settings(
    db: Session,
    *,
    actor_id,
    spreadsheet_id: str = "",
    service_account_json: str | None = None,
    api_key: str | None = None,
    clear_service_account: bool = False,
    clear_api_key: bool = False,
) -> SalesSettings:
    current = _read(db, SALES_KEY)
    value = dict(current.value)
    sid = _text(spreadsheet_id)
    if sid and not _valid_spreadsheet_id(sid):
        raise SettingsValidationError("Идентификатор таблицы указан неверно. Это часть ссылки между /d/ и /edit.")
    if sid:
        value["spreadsheet_id"] = sid
    else:
        value.pop("spreadsheet_id", None)

    if clear_service_account:
        value.pop("service_account_json", None)
        value.pop("credentials", None)
    elif service_account_json is not None and str(service_account_json).strip():
        _parse_service_account(str(service_account_json).strip())
        value["service_account_json"] = encrypt_secret(str(service_account_json).strip())
        value.pop("credentials", None)

    if clear_api_key:
        value.pop("api_key", None)
    elif api_key is not None and str(api_key).strip():
        raw = str(api_key).strip()
        if len(raw) > 4000 or any(ch.isspace() for ch in raw):
            raise SettingsValidationError("Google API key указан неверно")
        value["api_key"] = encrypt_secret(raw)

    _write(db, SALES_KEY, value, actor_id=actor_id)
    return get_sales_settings(db)


def reset_sales_settings(db: Session) -> None:
    delete_setting(db, SALES_KEY)


def _valid_spreadsheet_id(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value))


def ai_settings_payload(config: AISettings) -> dict:
    """Safe representation for administrators: never includes the raw token."""
    return {
        "configured": config.configured,
        "enabled": config.enabled,
        "api_key_present": config.token_present,
        "api_key_masked": mask_secret(config.api_key),
        "api_key_source": config.sources.get("api_key", "none"),
        "token_error": config.token_error,
        "model": config.model,
        "base_url": config.base_url,
        "http_referer": config.http_referer,
        "app_title": config.app_title,
        "sources": config.sources,
        "stored": config.stored,
        "updated_at": config.updated_at,
        "env": {
            "enabled": bool(getattr(settings, "openrouter_enabled", False)),
            "api_key_present": bool(_text(getattr(settings, "openrouter_api_key", ""))),
            "model": _text(getattr(settings, "openrouter_model", "")),
            "base_url": _text(getattr(settings, "openrouter_base_url", "")),
        },
        "secret_storage": "encrypted",
    }


def sales_settings_payload(config: SalesSettings) -> dict:
    return {
        "configured": config.configured,
        "spreadsheet_id": config.spreadsheet_id,
        "spreadsheet_url": (
            f"https://docs.google.com/spreadsheets/d/{config.spreadsheet_id}/edit"
            if _valid_spreadsheet_id(config.spreadsheet_id) else None
        ),
        "service_account_present": bool(config.service_account_json),
        "service_account_email": config.service_account_email,
        "api_key_present": bool(config.api_key),
        "api_key_masked": mask_secret(config.api_key),
        "credentials_error": config.credentials_error,
        "sources": config.sources,
        "stored": config.stored,
        "updated_at": config.updated_at,
        "env": {
            "spreadsheet_id_present": bool(_text(getattr(settings, "sales_links_spreadsheet_id", ""))),
            "service_account_present": bool(_text(getattr(settings, "sales_links_service_account_json", ""))),
            "api_key_present": bool(_text(getattr(settings, "sales_links_google_api_key", ""))),
        },
    }
