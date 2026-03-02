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

    try:
        return str(ipaddress.ip_address(v))
    except Exception:
        return None


def _forwarded_for_ip(forwarded: str) -> str | None:
    s = str(forwarded or "").strip()
    if not s:
        return None

    for chunk in [c.strip() for c in s.split(",") if c.strip()]:
        parts = [p.strip() for p in chunk.split(";") if p.strip()]
        for part in parts:
            if part.lower().startswith("for="):
                v = part.split("=", 1)[1].strip().strip('"').strip()
                ip = _normalize_ip(v)
                if ip:
                    return ip
    return None


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


def client_ip_from_request(request: Request) -> str | None:
    remote_ip = None
    try:
        remote_ip = str(getattr(getattr(request, "client", None), "host", None) or "").strip() or None
    except Exception:
        remote_ip = None

    if bool(getattr(settings, "trust_proxy_headers", False)) and _is_trusted_proxy(remote_ip):
        fwd = str(request.headers.get("forwarded") or "")
        ip = _forwarded_for_ip(fwd)
        if ip:
            return ip

        xri = _normalize_ip(str(request.headers.get("x-real-ip") or ""))
        if xri:
            return xri

        xff = str(request.headers.get("x-forwarded-for") or "")
        trusted = _parse_trusted_proxies(getattr(settings, "trusted_proxy_ips", None))
        ip = _xff_client_ip(xff, trusted)
        if ip:
            return ip

    ip = _normalize_ip(remote_ip)
    return ip
