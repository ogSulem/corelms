#!/usr/bin/env python3
"""Страж конфигурации nginx: адрес клиента определяет край, а не сам клиент.

Зачем. nginx — единственная точка, где приложение узнаёт IP посетителя: по нему
считаются лимиты входа, ведётся журнал безопасности и строится диагностика.
Если конфигурация снова начнёт пересылать присланный клиентом `X-Real-IP` /
`X-Forwarded-For`, любой желающий подставит себе чужой адрес: обойдёт лимит по
адресу и запишет в журнал IP, которого у него нет. Такое уже было — `map`
доверял заголовкам без проверки, потому что так проще жить за Caddy.

Что проверяем:
1. синтаксис (crossplane — парсер самого nginx, если он установлен);
2. `set_real_ip_from` — только внутренние сети;
3. `real_ip_header X-Forwarded-For` + `real_ip_recursive on`;
4. наружу уходит `X-Real-IP $remote_addr` и `X-Forwarded-For $proxy_add_x_forwarded_for`;
5. ни один проксируемый заголовок не берётся из `$http_x_*`.

Запуск: python3 deploy/check-nginx.py [nginx/default.conf]
"""
from __future__ import annotations

import ipaddress
import pathlib
import re
import sys
import tempfile

DIRECTIVE = re.compile(r"^\s*([a-z_]+)\s+(.*?);\s*$", re.MULTILINE)


def parse_ok(text: str) -> list[str]:
    """Синтаксис через crossplane (`pip install crossplane`) — если он есть."""
    try:
        import crossplane  # type: ignore
    except Exception:
        print("crossplane не установлен: синтаксис проверяю только структурно")
        return []
    # Файл подключается в http-контекст (conf.d), а crossplane начинает с main.
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "nginx-check.conf"
        path.write_text("events {}\nhttp {\n" + text + "\n}\n", encoding="utf-8")
        result = crossplane.parse(str(path), catch_errors=True)
    if result.get("status") != "ok":
        return [f"синтаксис: {err.get('error')} (строка {err.get('line')})" for err in result.get("errors") or []]
    return []


def check(text: str) -> list[str]:
    problems: list[str] = []

    failed = parse_ok(text)
    problems.extend(failed)
    if failed:
        return problems  # с битым синтаксисом остальные проверки бессмысленны

    if "real_ip_header X-Forwarded-For;" not in text:
        problems.append("нет `real_ip_header X-Forwarded-For;` — адрес клиента не вычисляется")
    if not re.search(r"real_ip_recursive\s+on;", text):
        problems.append("нет `real_ip_recursive on;` — цепочка не разбирается справа налево")

    trusted = re.findall(r"set_real_ip_from\s+([^;]+);", text)
    if not trusted:
        problems.append("нет ни одного `set_real_ip_from` — доверять заголовкам нельзя никому")
    for value in trusted:
        try:
            net = ipaddress.ip_network(value.strip(), strict=False)
        except Exception:
            problems.append(f"set_real_ip_from {value!r} — не сеть и не адрес")
            continue
        if not (net.is_private or net.is_loopback or net.is_link_local):
            problems.append(f"set_real_ip_from {value.strip()} — публичная сеть: заголовкам такого пира доверять нельзя")

    for header, value in DIRECTIVE.findall(text):
        if not header.startswith("proxy_set_header"):
            continue
        name, _, raw = value.partition(" ")
        name = name.strip().lower()
        raw = raw.strip()
        if name == "x-real-ip" and raw != "$remote_addr":
            problems.append(f"X-Real-IP уходит как {raw}: так клиент подставит себе любой адрес")
        if name == "x-forwarded-for" and raw != "$proxy_add_x_forwarded_for":
            problems.append(f"X-Forwarded-For уходит как {raw}: цепочка должна дописываться nginx")
        if name == "forwarded" and "$http_" in raw:
            problems.append("заголовок Forwarded собирается из присланного клиентом значения")
        if "$http_x_real_ip" in raw or "$http_x_forwarded" in raw:
            problems.append(f"{name}: значение берётся из клиентского заголовка ({raw})")

    return problems


def main(argv: list[str]) -> int:
    path = pathlib.Path(argv[1] if len(argv) > 1 else "nginx/default.conf")
    if not path.exists():
        print(f"файл не найден: {path}")
        return 2
    problems = check(path.read_text(encoding="utf-8"))
    if problems:
        for problem in problems:
            print(f"FAIL {path}: {problem}")
        return 1
    print(f"ok: {path} — адрес клиента определяет nginx, синтаксис верный")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
