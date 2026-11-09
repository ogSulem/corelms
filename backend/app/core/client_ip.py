from __future__ import annotations

import ipaddress

from fastapi import Request

from app.core.config import settings


def _parse_trusted_proxies(value: str | None) -> list[ipaddress._BaseNetwork]:
    raw = str(value or "").strip()
    if not raw:
        return []
    out: list[ipaddress._BaseNetwork] = []
    for part in [p.strip() for p in raw.split(",") if p.strip()]:
        try:
            if "/" in part:
                out.append(ipaddress.ip_network(part, strict=False))
            else:
                ip = ipaddress.ip_address(part)
                out.append(ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}", strict=False))
        except Exception:
            continue
    return out


def _is_trusted_proxy(remote_ip: str | None) -> bool:
    if not remote_ip:
        return False
    try:
        rip = ipaddress.ip_address(remote_ip)
    except Exception:
        return False

    nets = _parse_trusted_proxies(getattr(settings, "trusted_proxy_ips", None))
    if not nets:
        return False

    for n in nets:
        try:
            if rip in n:
                return True
        except Exception:
            continue
    return False


def _normalize_ip(value: str | None) -> str | None:
    v = str(value or "").strip().strip('"').strip()
    if not v:
        return None

    if v.startswith("[") and "]" in v:
        v = v[1 : v.index("]")]

    if ":" in v and not v.count(":") > 1:
        host = v.split(":", 1)[0].strip()
        if host:
            v = host

    # `fe80::1%eth0` — адрес с зоной интерфейса: `ip_address` такой не разбирает,
    # и клиент «пропадал» из лимитов и журнала.
    if "%" in v:
        v = v.split("%", 1)[0].strip()

    try:
        addr = ipaddress.ip_address(v)
    except Exception:
        return None
    # `::ffff:203.0.113.9` — тот же клиент, что `203.0.113.9`. Без приведения
    # у одного человека получались два разных ключа лимита и две карточки сессий.
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return str(addr)


def _xff_client_ip(xff: str, trusted_proxies: list[ipaddress._BaseNetwork]) -> str | None:
    raw = str(xff or "").strip()
    if not raw:
        return None

    chain: list[str] = []
    for part in [p.strip() for p in raw.split(",") if p.strip()]:
        ip = _normalize_ip(part)
        if ip:
            chain.append(ip)

    if not chain:
        return None

    if not trusted_proxies:
        return chain[0]

    for ip_s in reversed(chain):
        try:
            ip_o = ipaddress.ip_address(ip_s)
        except Exception:
            continue
        is_proxy = False
        for net in trusted_proxies:
            try:
                if ip_o in net:
                    is_proxy = True
                    break
            except Exception:
                continue
        if not is_proxy:
            return ip_s

    return chain[0]


def resolve_client_ip(request: Request) -> tuple[str | None, str]:
    """Адрес клиента и источник, откуда он взят: `x-real-ip`, `x-forwarded-for`, `direct`.

    Один разбор на всех: по нему считаются лимиты входа, пишется журнал
    безопасности и строится диагностика в админке. Раньше диагностика собирала
    источник своей копией правил и показывала `x-real-ip` даже когда заголовкам
    не доверяли — админ видел не тот адрес, который реально применялся.
    """
    remote_ip = None
    try:
        remote_ip = str(getattr(getattr(request, "client", None), "host", None) or "").strip() or None
    except Exception:
        remote_ip = None

    if bool(getattr(settings, "trust_proxy_headers", False)) and _is_trusted_proxy(remote_ip):
        # Порядок источников — от самого надёжного к самому подделываемому.
        #
        # X-Real-IP наш край (Caddy/nginx) выставляет сам и перезаписывает
        # присланное клиентом. X-Forwarded-For край дописывает справа, поэтому
        # настоящий адрес ищется справа налево (см. _xff_client_ip).
        #
        # Заголовок RFC 7239 `Forwarded` в нашем стеке не выставляет никто,
        # то есть его значение целиком приходит от клиента. Раньше он проверялся
        # ПЕРВЫМ — и любой мог подставить себе любой IP: обойти лимит входа по
        # адресу и подделать записи в журнале безопасности.
        xri = _normalize_ip(str(request.headers.get("x-real-ip") or ""))
        if xri:
            return xri, "x-real-ip"

        xff = str(request.headers.get("x-forwarded-for") or "")
        trusted = _parse_trusted_proxies(getattr(settings, "trusted_proxy_ips", None))
        ip = _xff_client_ip(xff, trusted)
        if ip:
            return ip, "x-forwarded-for"

        # `Forwarded` намеренно НЕ читаем: в нашем стеке его не формирует никто
        # (Caddy и nginx ставят X-Real-IP и X-Forwarded-For), значит значение
        # приходит только от клиента — и это готовый способ подставить себе
        # любой адрес. Если такой прокси появится, лучше показать адрес
        # соединения, чем поверить подделке.

    return _normalize_ip(remote_ip), "direct"


def client_ip_from_request(request: Request) -> str | None:
    return resolve_client_ip(request)[0]
