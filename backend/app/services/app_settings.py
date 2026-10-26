"""Runtime application settings that administrators can edit in the LMS.

Every integration resolves the same way:

1. values saved here (database, secrets encrypted at rest);
2. legacy Redis overrides (``runtime:llm`` / ``runtime:s3``) kept for upgrades;
3. process environment (``OPENROUTER_*``, ``SALES_LINKS_*``, ``S3_*``).

Resolution always happens in the process that needs the value, so RQ workers
see a token saved in the UI without a restart. No plaintext secret is ever
returned by the API.
"""
from __future__ import annotations

import json
import logging
import time
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
STORAGE_KEY = "storage"
PLATFORM_KEY = "platform"

LEGACY_STORAGE_KEY = "runtime:s3"


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


# --- Storage (S3) -----------------------------------------------------------
# Values live next to the other integrations: encrypted in the database, so
# they survive Redis restarts, cache expiry and key rotation (reported, not
# silently lost). The storage layer reads them on every call, therefore saving
# needs no restart. A short per-process cache keeps multipart uploads cheap.

STORAGE_FIELDS = (
    "s3_endpoint_url",
    "s3_public_endpoint_url",
    "s3_bucket",
    "s3_region_name",
    "s3_addressing_style",
)
STORAGE_SECRET_FIELDS = ("s3_access_key_id", "s3_secret_access_key")
_STORAGE_CACHE_TTL_SECONDS = 10.0
_storage_cache: tuple[float, dict[str, str]] | None = None


@dataclass(frozen=True)
class StorageSettings:
    endpoint_url: str
    public_endpoint_url: str
    bucket: str
    region_name: str
    addressing_style: str
    access_key_id: str
    secret_access_key: str
    sources: dict[str, str]
    stored: bool
    updated_at: str | None
    credentials_error: bool = False
    legacy: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.bucket)


def invalidate_storage_cache() -> None:
    global _storage_cache
    _storage_cache = None


def _legacy_storage() -> dict[str, str]:
    """Redis ``runtime:s3`` overrides written by older releases."""
    env = _text(getattr(settings, "app_env", "")).lower()
    if env in {"prod", "production"} and not bool(getattr(settings, "allow_runtime_s3_overrides", False)):
        return {}
    try:
        raw = get_redis().hgetall(LEGACY_STORAGE_KEY) or {}
    except Exception:
        log.debug("app_settings: legacy runtime:s3 is unavailable", exc_info=True)
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        k = key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else str(key)
        v = value.decode("utf-8", errors="ignore") if isinstance(value, (bytes, bytearray)) else str(value)
        if k in STORAGE_FIELDS or k in STORAGE_SECRET_FIELDS:
            out[k] = v.strip()
    return out


def get_storage_settings(db: Session | None = None) -> StorageSettings:
    row = _read(db, STORAGE_KEY)
    value = dict(row.value)
    # Rows written by early builds of this feature used the short names.
    for field in STORAGE_FIELDS + STORAGE_SECRET_FIELDS:
        short = field.replace("s3_", "")
        if field not in value and short in value:
            value[field] = value[short]
    legacy = _legacy_storage()
    sources: dict[str, str] = {}

    credentials_error = False
    stored_access = ""
    stored_secret = ""
    for field, target in (("s3_access_key_id", "access"), ("s3_secret_access_key", "secret")):
        raw = _text(value.get(field))
        if not raw:
            continue
        try:
            decoded = decrypt_secret(raw)
        except SecretDecryptError:
            credentials_error = True
            continue
        if target == "access":
            stored_access = decoded
        else:
            stored_secret = decoded

    env_access = _text(getattr(settings, "s3_access_key_id", ""))
    env_secret = _text(getattr(settings, "s3_secret_access_key", ""))
    legacy_access = _text(legacy.get("s3_access_key_id"))
    legacy_secret = _text(legacy.get("s3_secret_access_key"))

    access_key_id = str(_pick("access", stored_access, legacy_access, env_access, sources) or "")
    secret_access_key = str(_pick("secret", stored_secret, legacy_secret, env_secret, sources) or "")

    env_values = {
        "s3_endpoint_url": _text(getattr(settings, "s3_endpoint_url", "")),
        "s3_public_endpoint_url": _text(getattr(settings, "s3_public_endpoint_url", "")),
        "s3_bucket": _text(getattr(settings, "s3_bucket", "")),
        "s3_region_name": _text(getattr(settings, "s3_region_name", "")),
        "s3_addressing_style": _text(getattr(settings, "s3_addressing_style", "")),
    }
    resolved: dict[str, str] = {}
    for field in STORAGE_FIELDS:
        resolved[field] = str(
            _pick(field, _text(value.get(field)), _text(legacy.get(field)), env_values[field], sources) or ""
        )

    return StorageSettings(
        endpoint_url=resolved["s3_endpoint_url"],
        public_endpoint_url=resolved["s3_public_endpoint_url"],
        bucket=resolved["s3_bucket"],
        region_name=resolved["s3_region_name"],
        addressing_style=resolved["s3_addressing_style"],
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        sources=sources,
        stored=row.exists,
        updated_at=row.updated_at,
        # An unreadable stored key is only a problem when no fallback exists.
        credentials_error=bool(credentials_error and not (access_key_id or secret_access_key)),
        legacy=bool(legacy),
    )


def storage_overrides(db: Session | None = None) -> dict[str, str]:
    """Overrides that must win over ``S3_*`` environment values.

    Only explicitly saved or legacy values are returned, so call sites keep
    their existing ``override or settings.s3_...`` fallbacks. Cached briefly
    because every S3 call resolves it.
    """
    global _storage_cache
    now = time.monotonic()
    if db is None and _storage_cache is not None and now - _storage_cache[0] < _STORAGE_CACHE_TTL_SECONDS:
        return dict(_storage_cache[1])

    saved = _read(db, STORAGE_KEY).value
    for field in STORAGE_FIELDS + STORAGE_SECRET_FIELDS:
        short = field.replace("s3_", "")
        if field not in saved and short in saved:
            saved[field] = saved[short]
    out: dict[str, str] = {}
    for field in STORAGE_FIELDS:
        value = _text(saved.get(field))
        if value:
            out[field] = value
    for field in STORAGE_SECRET_FIELDS:
        raw = _text(saved.get(field))
        if not raw:
            continue
        try:
            out[field] = decrypt_secret(raw)
        except SecretDecryptError:
            log.warning("app_settings: stored S3 secret cannot be decrypted; enter it again", exc_info=False)
    # Legacy Redis values stay readable during an upgrade, but never win over
    # values saved in the interface.
    for field, value in _legacy_storage().items():
        out.setdefault(field, value)

    if db is None:
        _storage_cache = (now, dict(out))
    return out


def save_storage_settings(
    db: Session,
    *,
    actor_id,
    endpoint_url: str = "",
    public_endpoint_url: str = "",
    bucket: str = "",
    region_name: str = "",
    addressing_style: str = "",
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    clear_credentials: bool = False,
) -> StorageSettings:
    current = _read(db, STORAGE_KEY)
    value = dict(current.value)
    cleaned = {
        "s3_endpoint_url": _text(endpoint_url),
        "s3_public_endpoint_url": _text(public_endpoint_url),
        "s3_bucket": _text(bucket),
        "s3_region_name": _text(region_name),
        "s3_addressing_style": _text(addressing_style),
    }
    if not cleaned["s3_bucket"]:
        raise SettingsValidationError("Укажите имя bucket")
    for field, raw in cleaned.items():
        if len(raw) > 500:
            raise SettingsValidationError(f"{field}: слишком длинное значение")
    for field in ("s3_endpoint_url", "s3_public_endpoint_url"):
        cleaned[field] = _validate_http_url(cleaned[field], field=field.replace("s3_", "").replace("_", " ").capitalize())
    if cleaned["s3_addressing_style"] and cleaned["s3_addressing_style"] not in {"path", "virtual", "auto"}:
        raise SettingsValidationError("Стиль адресации: path, virtual или auto")
    if len(cleaned["s3_region_name"]) > 100:
        raise SettingsValidationError("Регион указан неверно")

    # Canonical ``s3_*`` keys are shared by the storage layer, the legacy Redis
    # hash and this row, so one name works everywhere.
    for field, raw in cleaned.items():
        if raw:
            value[field] = raw
        else:
            value.pop(field, None)

    if clear_credentials:
        value.pop("s3_access_key_id", None)
        value.pop("s3_secret_access_key", None)
    for field, raw in (("s3_access_key_id", access_key_id), ("s3_secret_access_key", secret_access_key)):
        candidate = _text(raw)
        if not candidate:
            continue
        if len(candidate) > 2000 or any(ch.isspace() for ch in candidate):
            raise SettingsValidationError(f"{field}: неверный формат ключа")
        value[field] = encrypt_secret(candidate)

    _write(db, STORAGE_KEY, value, actor_id=actor_id)
    invalidate_storage_cache()
    return get_storage_settings(db)


def reset_storage_settings(db: Session) -> None:
    delete_setting(db, STORAGE_KEY)
    try:
        get_redis().delete(LEGACY_STORAGE_KEY)
    except Exception:
        log.debug("app_settings: could not clear legacy runtime:s3", exc_info=True)
    invalidate_storage_cache()


def storage_settings_payload(config: StorageSettings) -> dict:
    """Safe storage representation: only masked credentials leave the server."""
    return {
        "configured": config.configured,
        "stored": config.stored,
        "updated_at": config.updated_at,
        "fields": {
            "s3_endpoint_url": config.endpoint_url if config.sources.get("s3_endpoint_url") == "database" else "",
            "s3_public_endpoint_url": config.public_endpoint_url if config.sources.get("s3_public_endpoint_url") == "database" else "",
            "s3_bucket": config.bucket if config.sources.get("s3_bucket") == "database" else "",
            "s3_region_name": config.region_name if config.sources.get("s3_region_name") == "database" else "",
            "s3_addressing_style": config.addressing_style if config.sources.get("s3_addressing_style") == "database" else "",
        },
        "access_key_masked": mask_secret(config.access_key_id),
        "secret_key_masked": mask_secret(config.secret_access_key),
        "sources": config.sources,
        "credentials_error": config.credentials_error,
        "legacy": config.legacy,
        "resolved": {
            "bucket": config.bucket,
            "endpoint_url": config.endpoint_url,
            "public_endpoint_url": config.public_endpoint_url,
            "region_name": config.region_name,
            "addressing_style": config.addressing_style,
        },
        "env": {
            "bucket": _text(getattr(settings, "s3_bucket", "")),
            "endpoint_url": _text(getattr(settings, "s3_endpoint_url", "")),
            "credentials_present": bool(_text(getattr(settings, "s3_access_key_id", ""))),
        },
        "secret_storage": "encrypted",
    }


# --- Platform limits --------------------------------------------------------


@dataclass(frozen=True)
class PlatformSettings:
    upload_max_bytes: int
    allow_public_register: bool
    sources: dict[str, str]
    stored: bool
    updated_at: str | None


MIN_UPLOAD_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024


def get_platform_settings(db: Session | None = None) -> PlatformSettings:
    row = _read(db, PLATFORM_KEY)
    value = row.value
    sources: dict[str, str] = {}

    env_upload = int(getattr(settings, "content_upload_max_bytes", 512 * 1024 * 1024) or 512 * 1024 * 1024)
    stored_upload = value.get("upload_max_bytes")
    upload = env_upload
    if isinstance(stored_upload, int) and MIN_UPLOAD_BYTES <= stored_upload <= MAX_UPLOAD_BYTES:
        upload, sources["upload_max_bytes"] = stored_upload, "database"
    else:
        sources["upload_max_bytes"] = "environment"

    env_register = bool(getattr(settings, "allow_public_register", False))
    stored_register = _bool(value.get("allow_public_register"))
    if stored_register is None:
        allow_register, sources["allow_public_register"] = env_register, "environment"
    else:
        allow_register, sources["allow_public_register"] = stored_register, "database"

    return PlatformSettings(
        upload_max_bytes=upload,
        allow_public_register=allow_register,
        sources=sources,
        stored=row.exists,
        updated_at=row.updated_at,
    )


def save_platform_settings(
    db: Session,
    *,
    actor_id,
    upload_max_bytes: int,
    allow_public_register: bool,
) -> PlatformSettings:
    if not isinstance(upload_max_bytes, int) or not (MIN_UPLOAD_BYTES <= upload_max_bytes <= MAX_UPLOAD_BYTES):
        raise SettingsValidationError("Размер файла должен быть от 1 МБ до 20 ГБ")
    current = _read(db, PLATFORM_KEY)
    value = dict(current.value)
    value["upload_max_bytes"] = int(upload_max_bytes)
    value["allow_public_register"] = bool(allow_public_register)
    _write(db, PLATFORM_KEY, value, actor_id=actor_id)
    return get_platform_settings(db)


def reset_platform_settings(db: Session) -> None:
    delete_setting(db, PLATFORM_KEY)


def platform_settings_payload(config: PlatformSettings) -> dict:
    return {
        "upload_max_bytes": config.upload_max_bytes,
        "allow_public_register": config.allow_public_register,
        "sources": config.sources,
        "stored": config.stored,
        "updated_at": config.updated_at,
        "env": {
            "upload_max_bytes": int(getattr(settings, "content_upload_max_bytes", 0) or 0),
            "allow_public_register": bool(getattr(settings, "allow_public_register", False)),
        },
        "limits": {"min_upload_bytes": MIN_UPLOAD_BYTES, "max_upload_bytes": MAX_UPLOAD_BYTES},
    }
