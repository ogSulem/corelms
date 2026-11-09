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


def test_cookie_secure_check_reports_what_the_browser_will_actually_get(client, admin_headers, monkeypatch):
    """Secure-кука на HTTP — не защита, а потерянная сессия на телефоне."""
    checks = lambda body: {item["key"]: item for item in body["checks"]}

    monkeypatch.setattr(settings, "cookie_secure", None)
    over_http = client.get("/admin/settings/security", headers={**admin_headers, "X-Forwarded-Proto": "http"}).json()
    assert over_http["cookies"]["access"]["effective_secure"] is False
    assert checks(over_http)["cookie_secure"]["ok"] is False
    assert "HTTP" in checks(over_http)["cookie_secure"]["detail"]

    over_https = client.get("/admin/settings/security", headers={**admin_headers, "X-Forwarded-Proto": "https"}).json()
    assert over_https["cookies"]["access"]["effective_secure"] is True
    assert checks(over_https)["cookie_secure"]["ok"] is True

    # Явный COOKIE_SECURE=false — это осознанное решение администратора.
    monkeypatch.setattr(settings, "cookie_secure", False)
    forced_off = client.get("/admin/settings/security", headers={**admin_headers, "X-Forwarded-Proto": "https"}).json()
    assert forced_off["cookies"]["access"]["effective_secure"] is False
    assert "COOKIE_SECURE=false" in checks(forced_off)["cookie_secure"]["detail"]


def test_forwarded_header_from_client_cannot_spoof_ip(client, admin_headers, monkeypatch):
    """Клиент не должен подменять себе IP заголовком RFC 7239 `Forwarded`.

    Раньше он проверялся первым, поэтому подделка давала обход лимита входа по
    адресу и ложные записи «вход с нового IP» в журнале безопасности.
    """
    import app.core.client_ip as client_ip_module

    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_ips", "127.0.0.1,10.0.0.0/8")
    monkeypatch.setattr(client_ip_module, "_is_trusted_proxy", lambda remote: True)
    response = client.get("/admin/settings/security", headers={
        **admin_headers,
        "Forwarded": "for=6.6.6.6",
        "X-Real-IP": "203.0.113.7",
        "X-Forwarded-For": "203.0.113.7",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["client"]["ip"] == "203.0.113.7"
    assert body["client"]["source"] == "x-real-ip"


def test_forwarded_header_is_ignored_when_real_ip_is_absent(client, admin_headers, monkeypatch):
    import app.core.client_ip as client_ip_module

    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_ips", "127.0.0.1,10.0.0.0/8")
    monkeypatch.setattr(client_ip_module, "_is_trusted_proxy", lambda remote: True)
    body = client.get("/admin/settings/security", headers={
        **admin_headers, "Forwarded": "for=6.6.6.6",
    }).json()
    # Ни X-Real-IP, ни X-Forwarded-For нет — остаётся адрес самого соединения.
    assert body["client"]["ip"] != "6.6.6.6"


def test_diagnostics_show_the_ip_actually_used_for_limits(client, admin_headers, monkeypatch):
    """Источник IP в диагностике обязан совпадать с тем, что применяют лимиты.

    Диагностика считала `source` своей копией правил и показывала `x-real-ip`,
    даже когда заголовкам не доверяют, — админ видел адрес, который нигде не
    используется, и не мог понять, почему лимит срабатывает не по клиенту.
    """
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.0/8")
    body = client.get("/admin/settings/security", headers={
        **admin_headers, "X-Real-IP": "198.51.100.5", "X-Forwarded-For": "198.51.100.5",
    }).json()
    assert body["proxy"]["trusted"] is False
    assert body["client"]["source"] == "direct"
    assert body["client"]["ip"] != "198.51.100.5"  # заголовку не доверяем

    import app.core.client_ip as client_ip_module
    from starlette.requests import Request

    monkeypatch.setattr(client_ip_module, "_is_trusted_proxy", lambda remote: True)
    request = Request({"type": "http", "headers": [(b"x-real-ip", b"198.51.100.5")],
                       "client": ("10.1.2.3", 443), "scheme": "https"})
    assert client_ip_module.resolve_client_ip(request) == ("198.51.100.5", "x-real-ip")


def test_cron_endpoint_is_closed_without_a_configured_secret(client, monkeypatch):
    """Служебная ручка чистки не должна быть доступна «просто так»."""
    monkeypatch.setattr(settings, "cron_secret", None)
    assert client.post("/health/cron/admin-uploads-cleanup").status_code == 404
    assert client.post("/health/cron/run-all").status_code == 404


def test_cron_endpoint_rejects_a_wrong_secret(client, monkeypatch, redis_memory):
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    assert client.post("/health/cron/admin-uploads-cleanup", headers={"x-cron-secret": "wrong"}).status_code == 403
    assert client.post("/health/cron/admin-uploads-cleanup").status_code == 403
    # Верный секрет проходит саму проверку доступа (сама ручка дальше требует
    # очередь, поэтому проверяем гвард напрямую, без HTTP и без Redis).
    from starlette.requests import Request
    from app.routers.health import _require_cron_secret

    _require_cron_secret(Request({"type": "http", "headers": [(b"x-cron-secret", b"s3cret")]}))
    with pytest.raises(Exception):
        _require_cron_secret(Request({"type": "http", "headers": [(b"x-cron-secret", b"nope")]}))


def test_ipv4_mapped_and_zone_scoped_addresses_are_normalized():
    """Один клиент — один ключ лимита, даже если прокси прислал IPv6-форму."""
    from app.core.client_ip import _normalize_ip

    assert _normalize_ip("::ffff:203.0.113.9") == "203.0.113.9"
    assert _normalize_ip("[::ffff:203.0.113.9]:5555") == "203.0.113.9"
    assert _normalize_ip("fe80::1%eth0") == "fe80::1"
    assert _normalize_ip(" 198.51.100.7 ") == "198.51.100.7"
    assert _normalize_ip("not-an-ip") is None
