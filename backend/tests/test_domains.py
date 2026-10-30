"""Кириллический домен в настройках не должен ломать вход и проверки.

`COOKIE_DOMAIN=edu.каркастайги.рф` — рабочий вариант: браузер получает punycode.
Раньше сравнение строк «как есть» давало ложную ошибку в настройках, роняло
`update.sh` на самопроверке и могло отклонить CORS-запрос.
"""
from __future__ import annotations

import pytest

from app.core.domains import ascii_host, ascii_origin, cookie_domain_for, split_origins
from app.core.config import settings


CYRILLIC = "edu.каркастайги.рф"
PUNYCODE = "edu.xn--80aaamzedb7cml.xn--p1ai"


def test_hosts_and_origins_are_normalized_to_ascii():
    assert ascii_host(CYRILLIC) == PUNYCODE
    assert ascii_host(f"{CYRILLIC}:443") == PUNYCODE
    assert ascii_host(f"https://{PUNYCODE}/dashboard") == PUNYCODE
    assert ascii_host("203.0.113.9:8080") == "203.0.113.9"
    assert ascii_origin(f"https://{CYRILLIC}/") == f"https://{PUNYCODE}"
    assert ascii_origin("https://example.com:443/") == "https://example.com"
    assert ascii_origin("http://localhost:3000") == "http://localhost:3000"


def test_origins_from_env_are_deduplicated_and_ascii():
    assert split_origins(f"https://{CYRILLIC}, https://{PUNYCODE}/, ") == [f"https://{PUNYCODE}"]


@pytest.mark.parametrize("configured,host,expected", [
    (CYRILLIC, PUNYCODE, PUNYCODE),          # домен и хост — одна и та же кириллица в разных формах
    (PUNYCODE, PUNYCODE, PUNYCODE),
    (".каркастайги.рф", PUNYCODE, "xn--80aaamzedb7cml.xn--p1ai"),  # общий вход на поддоменах
    (CYRILLIC, "203.0.113.9", None),         # телефон по IP: host-only, кука не теряется
    (CYRILLIC, "test.example.com", None),    # другой домен
    ("", PUNYCODE, None),
])
def test_cookie_domain_only_applies_to_matching_host(configured, host, expected):
    assert cookie_domain_for(configured, host) == expected


def test_security_posture_accepts_cyrillic_cookie_domain(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "cookie_domain", CYRILLIC)
    body = client.get("/admin/settings/security", headers={**admin_headers, "Host": PUNYCODE}).json()
    checks = {item["key"]: item for item in body["checks"]}
    assert checks["cookie_domain_matches"]["ok"] is True, checks["cookie_domain_matches"]
    assert checks["cookie_domain_matches"]["detail"] == f"COOKIE_DOMAIN={PUNYCODE}, запрос на {PUNYCODE}."


def test_security_posture_warns_when_cookie_domain_is_foreign(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "cookie_domain", CYRILLIC)
    body = client.get("/admin/settings/security", headers={**admin_headers, "Host": "test.example.com"}).json()
    checks = {item["key"]: item for item in body["checks"]}
    assert checks["cookie_domain_matches"]["ok"] is False
    # В ответе не должно быть «домен» кириллицей — браузер получит ASCII.
    assert checks["cookie_domain_matches"]["detail"].startswith(f"COOKIE_DOMAIN={PUNYCODE}")
    assert body["cookies"]["access"]["domain"] is None  # host-only, вход не ломается


def test_cors_accepts_punycode_origin_when_env_has_cyrillic(monkeypatch):
    """Браузер присылает punycode: с кириллицей в .env POST получал 403 invalid_origin."""
    from fastapi.testclient import TestClient
    from app.main import create_app

    monkeypatch.setattr(settings, "cors_allow_origins", f"https://{CYRILLIC}, http://testserver")
    with TestClient(create_app()) as fresh:
        allowed = fresh.post("/auth/token", data={"username": "nobody@example.test", "password": "x"},
                             headers={"Origin": f"https://{PUNYCODE}", "Host": PUNYCODE})
        assert allowed.status_code != 403, allowed.text
        assert allowed.json().get("error_code") != "invalid_origin"
        foreign = fresh.post("/auth/token", data={"username": "nobody@example.test", "password": "x"},
                             headers={"Origin": "https://evil.example", "Host": PUNYCODE})
        assert foreign.status_code == 403
        assert foreign.json()["error_code"] == "invalid_origin"
