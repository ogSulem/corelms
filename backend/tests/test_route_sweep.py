"""Сквозной обход всех GET-маршрутов: ни одного 5xx.

Ручные проверки экранов ловят только то, куда дошли руки. Здесь приложение само
перечисляет свои маршруты и запрашивает каждый с существующим идентификатором
(случайным) — ответом может быть 200, 404 или 422, но не 500. Так находятся
падающие диагностические и вспомогательные страницы, которые никто не открывает
в обычном сценарии.
"""
from __future__ import annotations

import re
import uuid

import pytest
from fastapi.routing import APIRoute

from app.models.user import UserRole

PARAM = re.compile(r"\{[^}]+\}")
# Потоковые ответы держат соединение открытым; файлы/скачивания проверяются
# отдельными тестами с фейковым хранилищем.
SKIP_MARKERS = ("/events", "/stream", "/export", "/download", "/preview", "/viewer", "/thumb", "/media")


def _get_paths(client) -> list[str]:
    paths: list[str] = []
    for route in client.app.routes:  # type: ignore[attr-defined]
        if not isinstance(route, APIRoute):
            continue
        if "GET" not in (route.methods or set()):
            continue
        if any(marker in route.path for marker in SKIP_MARKERS):
            continue
        if ":path}" in route.path:
            continue
        paths.append(route.path)
    return sorted(set(paths))


def _sweep(client, paths: list[str], headers: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for path in paths:
        url = PARAM.sub(str(uuid.uuid4()), path)
        try:
            response = client.get(url, headers=headers)
        except Exception as exc:  # noqa: BLE001 — падение хуже любого статуса
            problems.append(f"{path} → {type(exc).__name__}: {exc}")
            continue
        if response.status_code >= 500:
            problems.append(f"{path} → {response.status_code}: {response.text[:200]}")
    return problems


@pytest.fixture(scope="module")
def get_paths(client):
    paths = _get_paths(client)
    assert len(paths) > 60, f"маршруты не собрались: {len(paths)}"
    return paths


def test_no_get_route_returns_server_error_for_admin(client, make_user, storage, get_paths):
    _user, headers = make_user(UserRole.superadmin)
    problems = _sweep(client, get_paths, headers)
    assert not problems, "GET-маршруты отвечают ошибкой сервера:\n" + "\n".join(problems)


def test_no_get_route_returns_server_error_for_learner(client, make_user, storage, get_paths):
    _user, headers = make_user(UserRole.employee)
    problems = _sweep(client, get_paths, headers)
    assert not problems, "GET-маршруты падают у сотрудника:\n" + "\n".join(problems)
