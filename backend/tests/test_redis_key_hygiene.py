"""Гигиена ключей Redis: у каждого ключа должен быть срок жизни.

Классическая тихая утечка: `set(key, value)` и отдельный `expire(key, ttl)`.
Ключ без TTL переживает и падение между двумя командами, и перезапуск — Redis
постепенно съедает память, а найти виновника через полгода почти невозможно.
Здесь статический страж по коду приложения: `set` обязан задавать `ex=`, а
счётчики (`incr`) — получать TTL в той же транзакции.
"""
from __future__ import annotations

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

SET_CALL = re.compile(r"\.set\(")
EX_LITERAL = re.compile(r"\bex\s*=")
EXPIRE_NEAR = re.compile(r"\.expire\(")


def _files() -> list[pathlib.Path]:
    return sorted(APP.rglob("*.py"))


def test_every_redis_set_sets_a_ttl() -> None:
    offenders: list[str] = []
    for path in _files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not SET_CALL.search(line) or EX_LITERAL.search(line):
                continue
            # Смотрим на текущую и следующую строки: `set` + `expire` рядом.
            window = "\n".join(lines[index:index + 3])
            if EXPIRE_NEAR.search(window):
                offenders.append(f"{path.relative_to(APP.parent)}:{index + 1}: {line.strip()}")
    assert not offenders, (
        "Redis `set` без `ex=` и TTL отдельной командой — ключ может остаться навсегда:\n"
        + "\n".join(offenders)
    )


def test_counters_set_expiry_in_the_same_transaction() -> None:
    """`incr` без TTL в одной транзакции — тот же риск вечного ключа."""
    offenders: list[str] = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\.incr\((.{0,80}?)\)", text, re.DOTALL):
            start = match.start()
            context = text[max(0, start - 400):start + 400]
            if "pipe.incr(" in match.group(0):
                continue
            if re.search(r"\.expire\(|pipe\.expire\(", context):
                continue
            line = text[:start].count("\n") + 1
            offenders.append(f"{path.relative_to(APP.parent)}:{line}: {match.group(0)[:60]}")
    assert not offenders, "счётчик Redis без срока жизни:\n" + "\n".join(offenders)
