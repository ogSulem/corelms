"""Значения из .env — только стартовые. Сохранённое в интерфейсе важнее.

Пользователь формулирует это так: «из env начальные настройки, но в настройках
если поменять что-то — всё должно подтянуться». Тесты проверяют не ответ ручки
`/admin/settings/*`, а поведение: регистрация, срок жизни сессии, лимит загрузки.
"""

from __future__ import annotations

import json

import pytest


def _save_platform(client, headers, **fields):
    payload = {"upload_max_bytes": 512 * 1024 * 1024, "allow_public_register": False, **fields}
    response = client.put("/admin/settings/platform", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_registration_switch_in_the_ui_beats_env(client, admin_headers, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "allow_public_register", False)
    # В .env регистрация выключена — интерфейс включает её.
    _save_platform(client, admin_headers, allow_public_register=True)
    created = client.post("/auth/register", json={"name": "Новый человек", "email": "ui-toggle@example.test",
                                                  "password": "strong-pass-123"})
    assert created.status_code == 200, created.text

    # И наоборот: интерфейс выключает регистрацию, хотя .env её разрешает.
    monkeypatch.setattr(settings, "allow_public_register", True)
    _save_platform(client, admin_headers, allow_public_register=False)
    blocked = client.post("/auth/register", json={"name": "Ещё человек", "email": "ui-toggle-2@example.test",
                                                  "password": "strong-pass-123"})
    assert blocked.status_code == 403, blocked.text


def test_session_ttl_follows_the_ui_not_env(client, admin_headers, db, monkeypatch):
    from app.core.config import settings
    from app.services import auth_sessions

    monkeypatch.setattr(settings, "session_idle_timeout_hours", 12)
    _save_platform(client, admin_headers, session_idle_hours=1, session_absolute_days=2, session_refresh_days=3)
    # Настройки кэшируются на 30 секунд (горячий путь входа).
    auth_sessions._limits_cache = None

    from app.models.user import User, UserRole

    user = User(name="Проверка срока", role=UserRole.employee, password_hash="x", must_change_password=False)
    db.add(user)
    db.commit()

    from starlette.requests import Request

    access, refresh, sid = auth_sessions.issue_session(user, Request({"type": "http", "headers": [], "client": ("test", 0)}))
    assert access and refresh
    session = auth_sessions.get_session(sid)
    assert session is not None
    assert int(session["idle_ttl_seconds"]) == 3600, session
    limit = auth_sessions._limits()
    assert limit[1] == 3600 and limit[0] == 3 * 86400 and limit[2] == 2 * 86400


def test_upload_limit_from_the_ui_is_enforced_by_the_api(client, admin_headers, make_module, storage):
    module, _lesson, _quiz = make_module()
    _save_platform(client, admin_headers, upload_max_bytes=1024 * 1024, allow_public_register=False)
    response = client.post(f"/admin/content/modules/{module.id}/uploads", headers=admin_headers,
                           json={"revision": module.content_revision, "filename": "big.mp4",
                                 "size_bytes": 2 * 1024 * 1024})
    assert response.status_code == 413, response.text


def test_reset_returns_to_the_env_value(client, admin_headers, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "content_upload_max_bytes", 7 * 1024 * 1024)
    _save_platform(client, admin_headers, upload_max_bytes=13 * 1024 * 1024)
    overview = client.get("/admin/settings/overview", headers=admin_headers).json()
    assert overview["upload_max_bytes"] == 13 * 1024 * 1024
    removed = client.delete("/admin/settings/platform", headers=admin_headers)
    assert removed.status_code == 200, removed.text
    overview = client.get("/admin/settings/overview", headers=admin_headers).json()
    assert overview["upload_max_bytes"] == 7 * 1024 * 1024


def test_settings_payloads_never_return_secrets(client, admin_headers):
    client.put("/admin/settings/ai", headers=admin_headers, json={
        "enabled": True, "api_key": "sk-or-super-secret-token", "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini"})
    client.put("/admin/settings/storage", headers=admin_headers, json={
        "s3_bucket": "bucket", "s3_access_key_id": "AKIA-SECRET-KEY", "s3_secret_access_key": "very-secret-value"})
    for path in ("/admin/settings/ai", "/admin/settings/storage", "/admin/settings/sales", "/admin/settings/platform"):
        raw = client.get(path, headers=admin_headers).text
        assert "sk-or-super-secret-token" not in raw, path
        assert "AKIA-SECRET-KEY" not in raw, path
        assert "very-secret-value" not in raw, path
    # Маска ключа показывается, чтобы админ понимал, что ключ сохранён.
    ai = client.get("/admin/settings/ai", headers=admin_headers).json()
    assert ai["api_key_present"] is True
    assert ai["api_key_masked"] and ai["api_key_masked"] != "sk-or-super-secret-token"


def test_ai_temperature_and_timeout_come_from_the_ui(client, admin_headers, monkeypatch):
    """Значения из админки важнее .env и для реального вызова провайдера."""
    from app.core.config import settings
    from app.services import openrouter

    monkeypatch.setattr(settings, "openrouter_temperature", 0.2)
    monkeypatch.setattr(settings, "openrouter_timeout_read", 90.0)
    saved = client.put("/admin/settings/ai", headers=admin_headers, json={
        "enabled": True, "api_key": "sk-or-ui-token", "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini", "temperature": 0.9, "request_timeout": 240})
    assert saved.status_code == 200, saved.text
    payload = saved.json()["settings"]
    assert payload["temperature"] == 0.9 and payload["request_timeout"] == 240
    assert payload["sources"]["temperature"] == "database"
    # .env остаётся стартовым значением и виден администратору.
    assert payload["env"]["temperature"] == 0.2 and payload["env"]["request_timeout"] == 90.0

    captured: dict[str, object] = {}
    question = {"type": "single", "prompt": "Что такое LMS?\nA) Система\nB) Кофе\nC) Стул\nD) Лампа",
                "correct_answer": "A", "explanation": "По тексту урока это система обучения."}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            import json as _json

            return {"choices": [{"message": {"content": _json.dumps({"questions": [question]})}}]}

    class _Client:
        def __init__(self, timeout=None):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

        def post(self, url, json=None, headers=None):
            captured["payload"] = json
            return _Response()

    monkeypatch.setattr(openrouter.httpx, "Client", _Client)
    out = openrouter.generate_quiz_questions_openrouter(title="Урок", text="Текст урока про LMS", n_questions=1)
    assert out, "провайдер должен вернуть вопрос"
    assert captured["payload"]["temperature"] == 0.9
    assert captured["timeout"].read == 240.0


def test_ai_temperature_is_validated(client, admin_headers):
    for bad in ({"temperature": 3}, {"temperature": -1}, {"request_timeout": 1}, {"request_timeout": 5000}):
        response = client.put("/admin/settings/ai", headers=admin_headers, json={
            "enabled": True, "base_url": "https://openrouter.ai/api/v1", **bad})
        assert response.status_code == 422, (bad, response.text)


def test_ai_temperature_reset_returns_to_env(client, admin_headers, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "openrouter_temperature", 0.2)
    monkeypatch.setattr(settings, "openrouter_timeout_read", 90.0)
    client.put("/admin/settings/ai", headers=admin_headers, json={
        "enabled": True, "temperature": 1.1, "request_timeout": 300})
    assert client.get("/admin/settings/ai", headers=admin_headers).json()["temperature"] == 1.1
    assert client.delete("/admin/settings/ai", headers=admin_headers).status_code == 200
    reset = client.get("/admin/settings/ai", headers=admin_headers).json()
    assert reset["temperature"] == 0.2 and reset["request_timeout"] == 90.0


def test_generation_path_uses_the_ui_temperature(client, admin_headers, monkeypatch):
    """Даже путь «сгенерировать тест» берёт температуру и таймаут из админки."""
    from app.services import llm_handler

    client.put("/admin/settings/ai", headers=admin_headers, json={
        "enabled": True, "api_key": "sk-or-ui-token", "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini", "temperature": 0.7, "request_timeout": 200})

    calls: list[dict] = []

    def fake_generate(*, title, text, n_questions, debug_out=None, temperature=None, timeout_read_seconds=None, **kwargs):
        calls.append({"temperature": temperature, "timeout": timeout_read_seconds})
        return []

    monkeypatch.setattr(llm_handler, "generate_quiz_questions_openrouter", fake_generate)
    llm_handler.generate_quiz_questions_ai(title="Урок", text="Текст урока", n_questions=2, retries=0)
    assert calls, "генерация должна дойти до провайдера"
    assert calls[0]["temperature"] == 0.7
    assert calls[0]["timeout"] is None or calls[0]["timeout"] <= 200


def test_private_responses_are_not_cacheable(client, admin_headers, make_user):
    """Личные данные не должны оседать в кэше браузера или прокси."""
    _user, headers = make_user()

    for path in ("/me/profile", "/me/progress-summary", "/modules"):
        response = client.get(path, headers=headers)
        assert response.status_code < 400, (path, response.status_code)
        assert response.headers.get("cache-control") == "private, no-store", (path, response.headers.get("cache-control"))

    admin = client.get("/admin/settings/ai", headers=admin_headers)
    assert admin.headers.get("cache-control") == "private, no-store"
