"""Матрица прав: обычный сотрудник не проходит ни в один админский маршрут.

Проверка идёт по фактическому списку маршрутов приложения, а не по списку,
написанному руками: новый эндпоинт в `/admin` без гварда сразу уронит тест.
Ожидаемый ответ — отказ (401/403/404), а не 200 и не 500.
"""
from __future__ import annotations

import re
import uuid

import pytest
from fastapi.routing import APIRoute

from app.models.user import UserRole

PARAM = re.compile(r"\{[^}]+\}")
# Потоковые маршруты держат соединение открытым — в списке «должен отказать»
# они бесполезны, а тест бы завис.
SKIP_MARKERS = ("/events", "/stream", "/export")
# Эти методы читают библиотеку продаж: чтение разрешено любому вошедшему,
# мутации — только superadmin (отдельная проверка ниже).
SALES_PREFIX = "/sales/files"


def _admin_routes(client) -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for route in client.app.routes:  # type: ignore[attr-defined]
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not (path.startswith("/admin") or path.startswith(SALES_PREFIX)):
            continue
        if "{" in path and ":path}" in path:
            continue
        if any(marker in path for marker in SKIP_MARKERS):
            continue
        for method in sorted(route.methods or []):
            if method in {"HEAD", "OPTIONS"}:
                continue
            if path.startswith(SALES_PREFIX) and method == "GET":
                continue
            if path.startswith(SALES_PREFIX) and path.endswith("/download") and method == "GET":
                continue
            routes.append((method, path))
    return routes


def _request(client, method: str, path: str, headers: dict[str, str] | None):
    url = PARAM.sub(str(uuid.uuid4()), path)
    return client.request(method, url, headers=headers or {}, json={} if method in {"POST", "PUT", "PATCH"} else None)


@pytest.fixture(scope="module")
def routes(client):
    collected = _admin_routes(client)
    assert len(collected) > 50, f"маршруты не собрались: {len(collected)}"
    return collected


def test_employee_is_rejected_everywhere_in_admin(client, make_user, routes):
    _user, headers = make_user(UserRole.employee)
    leaks: list[str] = []
    for method, path in routes:
        response = _request(client, method, path, headers)
        if response.status_code < 400:
            leaks.append(f"{method} {path} → {response.status_code}")
        elif response.status_code >= 500:
            leaks.append(f"{method} {path} → {response.status_code} (ошибка сервера вместо отказа)")
    assert not leaks, "сотрудник прошёл в админские маршруты:\n" + "\n".join(leaks)


def test_partner_is_rejected_everywhere_in_admin(client, make_user, routes):
    _user, headers = make_user(UserRole.partner)
    leaks: list[str] = []
    for method, path in routes:
        response = _request(client, method, path, headers)
        if response.status_code < 400 or response.status_code >= 500:
            leaks.append(f"{method} {path} → {response.status_code}")
    assert not leaks, "партнёр прошёл в админские маршруты:\n" + "\n".join(leaks)


def test_anonymous_is_rejected_everywhere_in_admin(client, routes):
    leaks: list[str] = []
    for method, path in routes:
        response = _request(client, method, path, None)
        if response.status_code < 400 or response.status_code >= 500:
            leaks.append(f"{method} {path} → {response.status_code}")
    assert not leaks, "аноним прошёл в админские маршруты:\n" + "\n".join(leaks)


def test_admin_role_also_cannot_use_superadmin_only_endpoints(client, admin_headers):
    """Обычный admin не должен получать операции superadmin (например, продажи)."""
    samples = [
        ("POST", "/sales/files/sections"),
        ("POST", "/sales/files/upload-session"),
        ("DELETE", f"/sales/files/entries/{uuid.uuid4()}"),
    ]
    for method, path in samples:
        response = _request(client, method, path, admin_headers)
        assert response.status_code in {403, 404, 422}, f"{method} {path} → {response.status_code}"
