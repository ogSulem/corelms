"""Единые правила работы со временем.

Колонки в БД объявлены как `timestamptz`, но SQLite (и любой драйвер без
поддержки зоны) отдаёт «наивные» значения. Сравнение такого значения с
`datetime.now(timezone.utc)` падало с `TypeError: can't compare offset-naive and
offset-aware datetimes` — так отдавала 500 страница «Результаты».

Правило: всё, что приходит из БД, приводится к UTC-aware через `as_utc`, а
«сейчас» берётся из `utcnow`.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    """ISO-время с зоной: «сейчас» или приведённое значение.

    Строка без смещения (`2026-11-05T07:33:55`) для браузера означает локальное
    время: `new Date()` сдвигал импорт и попытки на часовой пояс зрителя. Всё,
    что уходит в JSON, обязано содержать `+00:00`/`Z`.
    """
    moment = as_utc(value) if value is not None else utcnow()
    return (moment or utcnow()).isoformat()


def parse_utc(value: object) -> datetime | None:
    """Разобрать ISO-время (в том числе записанное старыми версиями без зоны)."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return as_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


def as_utc(value: datetime | None) -> datetime | None:
    """Привести значение к UTC-aware. Наивное считается уже UTC (так его пишем)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
