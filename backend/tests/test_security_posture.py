"""Диагностика безопасности и настраиваемые сроки сессии.

Админ должен видеть, каким сервер видит клиента (IP, прокси, HTTPS, куки),
и уметь менять сроки сессии из интерфейса — без правки .env и перезапуска.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import auth_sessions


def _platform_payload(**overrides):
    payload = {"upload_max_bytes": 1024 * 1024, "allow_public_register": False}
    payload.update(overrides)
    return payload


def test_security_posture_reports_client_ip_behind_trusted_proxy(client, admin_headers, monkeypatch):
    import app.core.client_ip as client_ip_module

    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_ips", "127.0.0.1,10.0.0.0/8")
    # TestClient обращается с именем "testclient", а не с IP-адресом прокси.
    monkeypatch.setattr(client_ip_module, "_is_trusted_proxy", lambda remote: True)
    response = client.get("/admin/settings/security", headers={
        **admin_headers,
        "X-Forwarded-For": "203.0.113.9",
        "X-Forwarded-Proto": "https",
        "Host": "edu.example.test",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["client"]["ip"] == "203.0.113.9"
    assert body["client"]["source"] == "x-forwarded-for"
    assert body["proxy"]["trust_headers"] is True
    assert body["request"]["secure"] is True
    checks = {item["key"]: item for item in body["checks"]}
    assert set(checks) == {"https", "cookie_secure", "cookie_domain_matches", "trust_proxy", "session_order", "register"}
    assert checks["https"]["ok"] is True
    assert checks["session_order"]["ok"] is True


def test_security_posture_warns_when_proxy_is_not_trusted(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.0/8")
    body = client.get("/admin/settings/security", headers={**admin_headers, "X-Forwarded-For": "203.0.113.9"}).json()
    assert body["client"]["ip"] is None  # не подставляем заголовок от недоверенного адреса
    assert {item["key"]: item for item in body["checks"]}["trust_proxy"]["ok"] is False


def test_security_posture_is_admin_only(client, auth_headers):
    assert client.get("/admin/settings/security", headers=auth_headers).status_code == 403


def test_session_limits_are_editable_and_applied(client, admin_headers, db):
    from app.services.app_settings import get_platform_settings

    saved = client.put("/admin/settings/platform", headers=admin_headers,
                       json=_platform_payload(session_idle_hours=2, session_absolute_days=7, session_refresh_days=5))
    assert saved.status_code == 200, saved.text
    settings_payload = saved.json()["settings"]
    assert (settings_payload["session_idle_hours"], settings_payload["session_absolute_days"],
            settings_payload["session_refresh_days"]) == (2, 7, 5)
    assert settings_payload["sources"]["session_idle_hours"] == "database"
    assert get_platform_settings(db).session_idle_hours == 2

    auth_sessions.invalidate_limits()
    refresh, idle, absolute = auth_sessions._limits()
    assert idle == 2 * 3600
    assert absolute == 7 * 86400
    assert refresh == 5 * 86400


def test_session_limits_reject_absurd_values(client, admin_headers):
    bad = client.put("/admin/settings/platform", headers=admin_headers,
                     json=_platform_payload(session_idle_hours=0, session_absolute_days=999))
    assert bad.status_code == 422


def test_reset_returns_session_limits_to_server_defaults(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "session_idle_timeout_hours", 9)
    client.put("/admin/settings/platform", headers=admin_headers, json=_platform_payload(session_idle_hours=3))
    reset = client.delete("/admin/settings/platform", headers=admin_headers)
    assert reset.status_code == 200
    assert reset.json()["settings"]["session_idle_hours"] == 9
    assert reset.json()["settings"]["sources"]["session_idle_hours"] == "environment"
