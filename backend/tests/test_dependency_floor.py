"""Сторож зависимостей: версии не должны откатываться ниже безопасных.

Каждая запись здесь — исправленная версия из публичного advisory. Тест ловит
случай, когда обновление зависимостей «откатили», потому что сборка с новыми
версиями что-то сломала: молчаливое возвращение уязвимой версии недопустимо.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Пакет → минимальная безопасная версия и причина.
BACKEND_FLOORS: dict[str, tuple[tuple[int, ...], str]] = {
    # algorithm confusion + ресурсное истощение (GHSA-3qf3-8w2g-rqmx и др.)
    "python-jose": ((3, 4, 0), "CVE-2024-33663/33664"),
    # DoS на разборе multipart и x-www-form-urlencoded (публичный /auth/token)
    "python-multipart": ((0, 0, 22), "GHSA-v9pg-7xvm-68hf / GHSA-5rvq-cxj2-64vf"),
    # крафтовые PDF: RAM/бесконечный цикл при построении превью
    "pypdf": ((6, 0, 0), "серия GHSA по DoS в pypdf"),
}

FRONTEND_FLOORS: dict[str, tuple[str, tuple[int, ...], str]] = {
    # RCE в Image Optimization API, обход middleware, SSRF в rewrites
    "next": ("dependencies", (15, 5, 28), "CVE-2026-96889 (GHSA-2464-fhr4-w9xw)"),
    "eslint-config-next": ("devDependencies", (15, 5, 28), "та же версия, что и next"),
}


def _version_tuple(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(text or "").strip().lstrip("^~>=< ").split("."):
        digits = re.match(r"^\d+", chunk)
        if not digits:
            break
        parts.append(int(digits.group(0)))
    return tuple(parts)


def _backend_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    text = (REPO / "backend" / "requirements.txt").read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.\-\[\]]+)\s*==\s*([^\s;]+)", line)
        if match:
            pins[match.group(1).split("[")[0]] = match.group(2)
    return pins


def test_backend_dependencies_are_not_below_security_floor():
    pins = _backend_pins()
    assert pins, "requirements.txt не разобран"
    problems: list[str] = []
    for name, (floor, reason) in BACKEND_FLOORS.items():
        pinned = pins.get(name)
        if pinned is None:
            problems.append(f"{name}: не закреплён в requirements.txt")
            continue
        if _version_tuple(pinned) < floor:
            problems.append(f"{name}=={pinned} < {'.'.join(map(str, floor))} ({reason})")
    assert not problems, "уязвимые зависимости:\n" + "\n".join(problems)


def test_frontend_dependencies_are_not_below_security_floor():
    package = json.loads((REPO / "frontend" / "package.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    for name, (section, floor, reason) in FRONTEND_FLOORS.items():
        declared = str((package.get(section) or {}).get(name) or "")
        if not declared:
            problems.append(f"{name}: нет в {section}")
            continue
        if _version_tuple(declared) < floor:
            problems.append(f"{name} {declared} < {'.'.join(map(str, floor))} ({reason})")
    assert not problems, "уязвимые зависимости:\n" + "\n".join(problems)


def test_next_image_optimizer_is_disabled():
    """`next/image` в проекте не используется, а `/_next/image` — публичный RCE-вектор."""
    config = (REPO / "frontend" / "next.config.js").read_text(encoding="utf-8")
    assert re.search(r"images:\s*\{\s*unoptimized:\s*true\s*\}", config), "оптимизатор картинок включён"
    assert "poweredByHeader: false" in config
