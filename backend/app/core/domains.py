"""Домены и origin в ASCII (punycode).

Кириллический домен в `.env` — обычная практика: `PUBLIC_APP_URL=https://edu.каркастайги.рф`,
`CORS_ALLOW_ORIGINS=https://edu.каркастайги.рф`. Но браузер всегда присылает
ASCII (punycode), а `Origin` в заголовке тоже ASCII. Если сравнивать строки как
есть, получается ложное «не совпадает»: настройки показывают красную проверку,
CORS отвечает 403 `invalid_origin`, а кука с кириллическим доменом молча
отбрасывается браузером — вход «проходит», но сессии нет.

Поэтому все сравнения делаются только после приведения к ASCII.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def _idna(host: str) -> str:
    """Хост в ASCII. Уже ASCII-строка возвращается как есть (в нижнем регистре)."""
    value = str(host or "").strip().strip(".").lower()
    if not value:
        return ""
    if value.isascii():
        return value
    try:
        return value.encode("idna").decode("ascii").lower()
    except (UnicodeError, UnicodeDecodeError):
        return value


def ascii_host(value: str | None) -> str:
    """Хост без схемы, порта и пути: `edu.каркастайги.рф:443` → `edu.xn--80aaamzedb7cml.xn--p1ai`.

    Понимает и полный URL, и голый хост, и хост с портом, и IPv6 в скобках.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"//{raw}"
    try:
        host = urlsplit(raw).hostname or ""
    except ValueError:
        return ""
    return _idna(host)


def ascii_origin(value: str | None) -> str:
    """`https://edu.каркастайги.рф/` → `https://edu.xn--80aaamzedb7cml.xn--p1ai`.

    Порт сохраняется, только если он нестандартный для схемы: браузер присылает
    `Origin` уже без `:443`/`:80`, значит и в списке разрешённых он не нужен.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw.rstrip("/")
    host = _idna(parts.hostname or "")
    if not host:
        return raw.rstrip("/")
    scheme = (parts.scheme or "https").lower()
    netloc = host if ":" not in host else f"[{host}]"
    if parts.port and not _is_default_port(scheme, parts.port):
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((scheme, netloc, "", "", ""))


def _is_default_port(scheme: str, port: int) -> bool:
    return (scheme == "https" and port == 443) or (scheme == "http" and port == 80)


def split_origins(value: str | None) -> list[str]:
    """Список origin из `CORS_ALLOW_ORIGINS`, приведённый к ASCII и без дублей."""
    result: list[str] = []
    for item in str(value or "").split(","):
        origin = ascii_origin(item)
        if origin and origin not in result:
            result.append(origin)
    return result


def cookie_domain_for(configured: str | None, host: str | None) -> str | None:
    """Домен для Set-Cookie с учётом фактического хоста запроса.

    Браузер молча выбрасывает куку, если её `Domain` не совпадает с адресом
    страницы. Поэтому настроенный домен применяется только к своему хосту и его
    поддоменам; в остальных случаях кука ставится host-only — вход работает с
    любого адреса (IP, временный домен, punycode).
    """
    domain = _idna(str(configured or "").strip().lstrip("."))
    current = ascii_host(host)
    if not domain:
        return None
    if not current:
        return domain
    if current == domain or current.endswith(f".{domain}"):
        return domain
    return None
