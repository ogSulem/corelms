"""Обход всех маршрутов записи: ни один не падает в 500 на пустом теле.

GET-обход (`test_route_sweep.py`) ловит падения экранов. Здесь то же самое для
POST/PUT/PATCH/DELETE: приложение само перечисляет свои маршруты и отправляет
каждый с пустым JSON. Ответом может быть 2xx, 4xx (неверное тело, нет прав,
нет объекта), но не 500 — пятисотка означает необработанную ветку, которую в
обычном сценарии никто не проверяет.
"""
from __future__ import annotations

import re
import uuid

import pytest
from fastapi.routing import APIRoute

from app.models.user import UserRole

PARAM = re.compile(r"\{[^}]+\}")

# Потоки, файлы и долгие задачи проверяются своими тестами: здесь только форма
# запроса. `/complete` с пустым телом заведомо уводит в работу с диском.
SKIP_MARKERS = (
    "/events", "/stream", "/download", "/preview", "/viewer", "/thumb", "/media",
    "/uploads/", "/upload", "/import-zip", "/multipart", "/transcode", "/purge",
    "/delete", "/restore-version", "/reimport", "/cron/",
)


def _write_paths(client) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for route in client.app.routes:  # type: ignore[attr-defined]
        if not isinstance(route, APIRoute):
            continue
        methods = {m for m in (route.methods or set()) if m in {"POST", "PUT", "PATCH", "DELETE"}}
        if not methods:
            continue
        if any(marker in route.path for marker in SKIP_MARKERS):
            continue
        if ":path}" in route.path:
            continue
        for method in sorted(methods):
            out.append((method, route.path))
    return sorted(set(out))


@pytest.fixture(scope="module")
def write_paths(client):
    paths = _write_paths(client)
    assert len(paths) > 40, f"маршруты не собрались: {len(paths)}"
    return paths


def _sweep(client, paths, headers) -> list[str]:
    problems: list[str] = []
    for method, path in paths:
        url = PARAM.sub(str(uuid.uuid4()), path)
        try:
            response = client.request(method, url, json={}, headers=headers)
        except Exception as exc:  # noqa: BLE001 — падение хуже любого статуса
            problems.append(f"{method} {path} → {type(exc).__name__}: {exc}")
            continue
        # 502/503/504 — осознанные ответы «сервис недоступен» (Redis, S3, очередь).
        # 500 означает необработанное исключение: его здесь быть не должно.
        if response.status_code >= 500 and response.status_code not in {502, 503, 504}:
            problems.append(f"{method} {path} → {response.status_code}: {response.text[:200]}")
    return problems


def test_admin_write_routes_never_500(client, write_paths, admin_headers):
    assert _sweep(client, write_paths, admin_headers) == []


def test_learner_write_routes_answer_with_rights_or_validation(client, write_paths, make_user):
    _, headers = make_user(UserRole.employee)
    assert _sweep(client, write_paths, headers) == []
