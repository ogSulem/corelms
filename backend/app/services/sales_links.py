from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.core.config import settings
from app.core.queue import release_job_lock
from app.core.redis_client import get_redis
from app.services.google_sheets import read_sales_snapshot

log = logging.getLogger(__name__)
_memory: dict[str, tuple[dict, float]] = {}
_refresh_lock = threading.Lock()
_errors: dict[str, float] = {}


def safe_link(value: object) -> str | None:
    url = str(value or "").strip()
    if not url or len(url) > 2000 or "\\" in url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        _ = parts.port  # Invalid/out-of-range ports are rejected, not passed to the browser.
        return url
    except ValueError:
        return None


def parse_snapshot(snapshot: dict) -> tuple[list[dict], list[str]]:
    blocks, warnings = [], []
    invalid = 0
    for title, rows in snapshot["sheets"]:
        if not rows:
            continue
        header = [str(x or "").strip().lower() for x in rows[0]]
        video = header[:3] in (["tab", "name", "link"], ["вкладка", "название", "ссылка"], ["раздел", "название", "ссылка"])
        simple = header[:2] in (["name", "link"], ["название", "ссылка"])
        if not video and not simple:
            warnings.append(f"Лист «{title}»: ожидаются столбцы name/link или tab/name/link.")
            continue
        links, tabs = [], {}
        for row in rows[1:]:
            if not any(str(cell).strip() for cell in row):
                continue
            offset = 1 if video else 0
            name = str(row[offset] if len(row) > offset else "").strip()[:300]
            link = safe_link(row[offset + 1] if len(row) > offset + 1 else "")
            group = str(row[0] if video and row else "").strip()[:200]
            if not name or not link or (video and not group):
                invalid += 1
                continue
            item = {"title": name, "url": link}
            if video:
                tabs.setdefault(group, []).append(item)
            else:
                links.append(item)
        blocks.append({"id": title, "title": title, "kind": "video", "tabs": [
            {"id": group, "label": group, "links": items} for group, items in tabs.items()]} if video else {
            "id": title, "title": title, "kind": "links", "links": links})
    if invalid:
        warnings.append(f"Пропущено незаполненных строк или небезопасных ссылок: {invalid}. Разрешены только http и https.")
    if snapshot.get("truncated"):
        warnings.append("Применён лимит: первые 30 листов и 1000 строк данных на лист. Разделите слишком большую таблицу.")
    return blocks, warnings


def source_url() -> str | None:
    sid = str(settings.sales_links_spreadsheet_id or "").strip()
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit" if re.fullmatch(r"[A-Za-z0-9_-]{1,200}", sid) else None


def _fallback(cached: dict | None, message: str, *, refreshing: bool = False) -> dict:
    return {**(cached or {"blocks": [], "last_success_at": None, "warnings": []}),
            "status": "stale" if cached else "loading" if refreshing else "error", "message": message, "refreshing": refreshing}


def get_sales_links_payload(*, bypass_cache: bool = False) -> dict:
    sid = str(settings.sales_links_spreadsheet_id or "").strip()
    creds = str(settings.sales_links_service_account_json or "").strip()
    api_key = str(settings.sales_links_google_api_key or "").strip()
    if not sid or (not creds and not api_key):
        return {"blocks": [], "status": "unconfigured", "last_success_at": None, "warnings": [],
                "message": "Google Sheets ещё не настроены. Файлы продаж доступны независимо от таблицы."}
    if source_url() is None:
        return _fallback(None, "Проверьте идентификатор таблицы в настройках сервера.")
    key = f"sales:links:v3:{sid}"
    token = uuid.uuid4().hex
    redis = None
    cached, fresh_until = _memory.get(key, (None, 0))
    if cached:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(cached["last_success_at"])
            if age.total_seconds() > 7 * 86400:
                cached, fresh_until = None, 0
        except (KeyError, TypeError, ValueError):
            cached, fresh_until = None, 0
    try:
        redis = get_redis()
        raw = redis.get(key + ":good")
        if raw:
            decoded = json.loads(raw)
            if isinstance(decoded, dict) and isinstance(decoded.get("blocks"), list):
                cached = decoded
        if not bypass_cache and redis.get(key + ":error"):
            return _fallback(cached, "Google Sheets временно недоступны. Показана последняя успешная копия, если она есть.")
        fresh = redis.get(key + ":fresh")
        if not bypass_cache and fresh:
            decoded = json.loads(fresh)
            if isinstance(decoded, dict) and isinstance(decoded.get("blocks"), list):
                return decoded
        if not redis.set(key + ":refresh", token, nx=True, ex=60):
            return _fallback(cached, "Обновляем данные из Google Sheets…", refreshing=True)
    except Exception:
        redis = None
        if not bypass_cache and fresh_until > time.monotonic() and cached:
            return cached
        if not bypass_cache and _errors.get(key, 0) > time.monotonic():
            return _fallback(cached, "Google Sheets временно недоступны. Показана последняя успешная копия, если она есть.")
    locked = _refresh_lock.acquire(blocking=False)
    if not locked:
        if redis:
            try:
                release_job_lock(redis, key + ":refresh", token)
            except Exception:
                pass
        return _fallback(cached, "Обновляем данные из Google Sheets…", refreshing=True)
    try:
        snapshot = read_sales_snapshot(spreadsheet_id=sid, creds_json=creds or None, api_key=api_key or None)
        blocks, warnings = parse_snapshot(snapshot)
        payload = {"blocks": blocks, "status": "fresh", "last_success_at": datetime.now(timezone.utc).isoformat(),
                   "warnings": warnings, "message": None, "refreshing": False}
        _memory[key] = payload, time.monotonic() + 180
        _errors.pop(key, None)
        if len(_memory) > 8:
            _memory.pop(next(iter(_memory)))
        if redis:
            try:
                encoded = json.dumps(payload, ensure_ascii=False)
                redis.setex(key + ":fresh", 180, encoded)
                redis.setex(key + ":good", 7 * 86400, encoded)
                redis.delete(key + ":error")
            except Exception:
                log.info("Sales cache unavailable; retaining an in-process copy")
        return payload
    except Exception as exc:
        # Exception URLs may contain an API key. Do not log the URL/body/credentials.
        log.warning("Sales Sheets refresh failed (%s)", type(exc).__name__)
        _errors[key] = time.monotonic() + 60
        if len(_errors) > 8:
            _errors.pop(next(iter(_errors)))
        if cached:
            _memory[key] = cached, 0
        if redis:
            try:
                redis.delete(key + ":fresh")
                redis.setex(key + ":error", 60, "unavailable")
            except Exception:
                pass
        return _fallback(cached, "Не удалось обновить Google Sheets. Сохранена последняя успешная копия; проверьте доступ к таблице.")
    finally:
        _refresh_lock.release()
        if redis:
            try:
                release_job_lock(redis, key + ":refresh", token)
            except Exception:
                pass
