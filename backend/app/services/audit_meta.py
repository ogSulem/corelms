"""Единые правила выдачи «меты» событий наружу.

Журналы (обучение и безопасность) пишут во внутренние поля то, что полезно
серверу: ключ объекта в хранилище, отпечаток устройства, идентификаторы. В
интерфейс это уходить не должно. Раньше каждый роутер фильтровал мету сам, и
`GET /me/recent-activity` отдавал `meta` как есть — вместе с `object_key`
(внутренний путь файла в S3). Теперь фильтр один на всех; старые строки в базе
(платформа работает не первый месяц) чистятся на чтении.
"""

from __future__ import annotations

import json

# Значения `LearningEvent.meta`, которые не являются JSON-объектом и значат
# ровно то, чем выглядят: «прочитано» и «модуль открыт».
PLAIN_LEARNING_META = {"read", "module_open"}

# Никогда не отдаём наружу, даже если поле появится в новой версии писателя.
LEARNING_META_DENY = {
    "object_key",
    "bucket",
    "device_hash",
    "token",
    "access_token",
    "refresh_token",
    "refresh",
    "password",
    "password_hash",
    "secret",
    "api_key",
}

# Продуктовые поля, которые интерфейсу действительно нужны.
LEARNING_META_ALLOW = {
    "action",
    "filename",
    "mime_type",
    "quiz_id",
    "attempt_no",
    "score",
    "passed",
    "correct",
    "total",
    "time_spent_seconds",
    "module_id",
    "submodule_id",
}

SECURITY_META_ALLOW = ("ip", "ip_fp", "user_agent", "new_device", "new_ip")

MAX_PLAIN_META_CHARS = 40
MAX_VALUE_CHARS = 300


def _clean_value(value: object) -> object:
    if isinstance(value, str):
        return value.replace("\x00", "").strip()[:MAX_VALUE_CHARS]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def parse_meta(raw: str | None) -> dict | None:
    """`meta` из базы → объект. Не JSON или не объект → None."""
    text = str(raw or "").strip()
    if not text or not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def sanitize_security_meta(meta: dict | None) -> str | None:
    if not isinstance(meta, dict) or not meta:
        return None
    clean: dict[str, object] = {}
    for key in SECURITY_META_ALLOW:
        if key not in meta:
            continue
        value = meta.get(key)
        if isinstance(value, bool):
            clean[key] = value
            continue
        value = _clean_value(value)
        if value is None or str(value).strip() == "":
            continue
        clean[key] = value
    if not clean:
        return None
    return json.dumps(clean, ensure_ascii=False)


def sanitize_learning_meta(meta: dict | None) -> str | None:
    if not isinstance(meta, dict) or not meta:
        return None
    clean: dict[str, object] = {}
    for key in LEARNING_META_ALLOW:
        if key in LEARNING_META_DENY or key not in meta:
            continue
        value = _clean_value(meta[key])
        if value is None or str(value).strip() == "":
            continue
        clean[key] = value
    if not clean:
        return None
    return json.dumps(clean, ensure_ascii=False)


def learning_meta_for_client(raw: str | None) -> str | None:
    """Сырое `LearningEvent.meta` из базы → безопасная строка для интерфейса."""
    text = str(raw or "").strip()
    if not text:
        return None
    if text.lower() in PLAIN_LEARNING_META:
        return text.lower()
    # Очень длинный не-JSON хвост (мусор из прошлых версий) наружу не тащим.
    if not text.startswith("{"):
        return text[:MAX_PLAIN_META_CHARS]
    return sanitize_learning_meta(parse_meta(text))
