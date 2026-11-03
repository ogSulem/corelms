"""Сплошной обход маршрутов: ни один GET не должен отвечать 500.

Это «сканер», а не проверка бизнес-логики: он ловит падения на пустых данных,
несуществующих идентификаторах и забытых null-проверках — то, что не видно в
точечных тестах, но всплывает у первого же пользователя.

Правила:
* подставляем валидные, но несуществующие UUID — обработчик обязан вернуть
  403/404/409/422, а не 500;
* стриминговые и SSE-маршруты пропускаем: они держат соединение открытым;
* для не-админа любой `/admin/...` обязан быть закрыт (401/403).
"""

import uuid

import pytest

from app.main import create_app

SKIP_MARKERS = ("/events", "stream", "/logs", "download", "/health")
ALLOWED = {200, 201, 202, 204, 206, 400, 401, 403, 404, 405, 409, 410, 413, 415, 416, 422, 429, 501, 503}


def _get_routes():
    seen = set()
    for route in create_app().routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if "GET" not in methods or not path.startswith(("/", "admin")):
            continue
        if not path.startswith("/") or path.startswith(("/api/", "/docs", "/redoc", "/openapi")):
            continue
        if any(marker in path for marker in SKIP_MARKERS):
            continue
        if path in seen:
            continue
        seen.add(path)
        yield path


def _concrete(path: str) -> str:
    import re
    # Все параметры пути заменяем на случайный UUID: формат валиден, объекта нет.
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


@pytest.mark.parametrize("path", list(_get_routes()))
def test_employee_get_never_crashes(client, make_user, path):
    _, headers = make_user()
    response = client.get(_concrete(path), headers=headers)
    assert response.status_code != 500, f"{path} → 500: {response.text[:400]}"
    assert response.status_code in ALLOWED, f"{path} → {response.status_code}"
    if path.startswith("/admin"):
        assert response.status_code in {401, 403}, f"{path} открыт для сотрудника: {response.status_code}"


@pytest.mark.parametrize("path", list(_get_routes()))
def test_admin_get_never_crashes(client, admin_headers, path):
    response = client.get(_concrete(path), headers=admin_headers)
    assert response.status_code != 500, f"{path} → 500: {response.text[:400]}"
    assert response.status_code in ALLOWED, f"{path} → {response.status_code}"
