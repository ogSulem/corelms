"""Политика входа, настраиваемая из админки.

Минимальная длина пароля и предел попыток входа раньше были только в `.env`:
администратор не мог ужесточить их из интерфейса, а три места проверки пароля
дублировали одно и то же условие. Здесь единая точка правды — значение из
админки, при отсутствии сохранённого — значение окружения.

Ниже 8 символов политику опустить нельзя: это защита от «настройки», которая
ослабляет вход до одного символа.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.app_settings import (
    MAX_LOGIN_ATTEMPTS,
    MAX_PASSWORD_LENGTH,
    MIN_LOGIN_ATTEMPTS,
    MIN_PASSWORD_LENGTH,
    get_platform_settings,
)


def _clamp(value: object, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def password_min_length(db: Session | None = None) -> int:
    """Минимальная длина пароля: админка → env → безопасное значение по умолчанию."""
    fallback = _clamp(getattr(settings, "password_min_length", 8), MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH, 8)
    try:
        return _clamp(get_platform_settings(db).password_min_length, MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH, fallback)
    except Exception:  # БД недоступна — не блокируем смену пароля из-за настроек.
        return fallback


def login_attempts_per_minute(db: Session | None = None) -> int:
    fallback = _clamp(getattr(settings, "login_attempts_per_minute", 10), MIN_LOGIN_ATTEMPTS, MAX_LOGIN_ATTEMPTS, 10)
    try:
        return _clamp(get_platform_settings(db).login_attempts_per_minute, MIN_LOGIN_ATTEMPTS, MAX_LOGIN_ATTEMPTS,
                      fallback)
    except Exception:
        return fallback


def password_problem(password: str, *, db: Session | None = None) -> str | None:
    """Почему пароль не годится. None — годится.

    Проверяем ровно то, что обещает интерфейс: длину и «не только пробелы».
    Требования к регистру и спецсимволам не вводим — они вынуждают людей
    записывать пароль на бумажке.
    """
    value = str(password or "")
    if not value.strip():
        return "Пароль не может быть пустым или состоять из пробелов"
    minimum = password_min_length(db)
    if len(value) < minimum:
        return f"Пароль должен быть не короче {minimum} символов"
    return None


def ensure_password_or_400(password: str, *, db: Session | None = None) -> None:
    """Проверить пароль для эндпоинтов, которые отвечают `400 password too short`."""
    if not password or len(str(password)) < password_min_length(db):
        raise HTTPException(status_code=400, detail="password too short")


def ensure_password_complexity_or_422(password: str, *, db: Session | None = None) -> None:
    """Проверка с внятным русским текстом (смена пароля, регистрация через админку)."""
    problem = password_problem(password, db=db)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
