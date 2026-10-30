"""Пустая строка в .env не должна ронять backend.

`COOKIE_SECURE=` — рекомендуемое значение (Secure только на HTTPS). Раньше
pydantic не мог разобрать пустую строку как bool, контейнер падал на старте, и
весь сайт отвечал 502 без внятной причины.
"""
from __future__ import annotations

from app.core.config import Settings


def test_blank_boolean_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "")
    monkeypatch.setenv("HEALTH_READY_CHECK_S3", "")
    settings = Settings()
    assert settings.cookie_secure is None
    assert settings.trust_proxy_headers is False
    assert settings.health_ready_check_s3 is True


def test_boolean_env_accepts_human_values(monkeypatch):
    for raw, expected in [("true", True), ("1", True), ("YES", True), ("false", False), ("0", False), ("off", False)]:
        monkeypatch.setenv("TRUST_PROXY_HEADERS", raw)
        assert Settings().trust_proxy_headers is expected, raw


def test_cyrillic_cookie_domain_is_kept_for_normalization(monkeypatch):
    monkeypatch.setenv("COOKIE_DOMAIN", "edu.каркастайги.рф")
    assert Settings().cookie_domain == "edu.каркастайги.рф"
    monkeypatch.setenv("COOKIE_DOMAIN", "")
    assert Settings().cookie_domain is None
