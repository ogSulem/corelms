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


def as_utc(value: datetime | None) -> datetime | None:
    """Привести значение к UTC-aware. Наивное считается уже UTC (так его пишем)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
