"""Время в JSON всегда с зоной — иначе браузер сдвигает его на свой пояс.

Наивное `2026-11-05T07:33:55` для `new Date()` означает локальное время, поэтому
в Москве импорт, попытки и история показывались на три часа позже реального.
Здесь три уровня проверки: сам помощник, реальные ответы API и запрет на
возврат `datetime.utcnow()`/`utcfromtimestamp` в код приложения.
"""
from __future__ import annotations

import pathlib
import re
from datetime import datetime, timedelta, timezone

from app.core.timeutil import parse_utc, utc_iso, utcnow

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MSK = timezone(timedelta(hours=3))


def test_naive_value_gets_utc_offset():
    assert utc_iso(datetime(2026, 11, 5, 7, 33)) == "2026-11-05T07:33:00+00:00"


def test_aware_value_is_converted_not_relabelled():
    # 10:33 по Москве — это 07:33 UTC, а не «10:33 UTC».
    assert utc_iso(datetime(2026, 11, 5, 10, 33, tzinfo=MSK)) == "2026-11-05T07:33:00+00:00"


def test_now_has_offset_and_is_close_to_real_time():
    value = utc_iso()
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 30


def test_parse_utc_accepts_all_formats_we_write():
    assert parse_utc("2026-11-05T07:33:55") == datetime(2026, 11, 5, 7, 33, 55, tzinfo=timezone.utc)
    assert parse_utc("2026-11-05T07:33:55+00:00") == datetime(2026, 11, 5, 7, 33, 55, tzinfo=timezone.utc)
    assert parse_utc("2026-11-05T10:33:55+03:00") == datetime(2026, 11, 5, 7, 33, 55, tzinfo=timezone.utc)
    assert parse_utc("2026-11-05T07:33:55Z") == datetime(2026, 11, 5, 7, 33, 55, tzinfo=timezone.utc)
    assert parse_utc("") is None
    assert parse_utc("не время") is None
    assert parse_utc(None) is None


def test_admin_user_payload_timestamps_have_zone(client, admin_headers, make_user):
    make_user()
    response = client.get("/admin/users", headers=admin_headers)
    assert response.status_code == 200, response.text
    items = [item for item in response.json()["items"] if item.get("created_at")]
    assert items, "в списке пользователей нет ни одной даты создания"
    for item in items:
        created = datetime.fromisoformat(item["created_at"])
        assert created.tzinfo is not None, item["created_at"]
        assert item["created_at"].endswith("+00:00")


def test_profile_and_history_payloads_have_zone(client, make_user):
    user, headers = make_user()
    profile = client.get("/me/profile", headers=headers)
    assert profile.status_code == 200, profile.text
    if profile.json().get("last_activity_at"):
        assert datetime.fromisoformat(profile.json()["last_activity_at"]).tzinfo is not None
    history = client.get("/me/history", headers=headers)
    assert history.status_code == 200, history.text
    for item in history.json().get("items", [])[:20]:
        raw = str(item.get("created_at") or "")
        if raw:
            assert datetime.fromisoformat(raw).tzinfo is not None, raw


def test_application_code_never_writes_naive_utc():
    """Страж: `datetime.utcnow()` и `utcfromtimestamp` возвращают время без зоны."""
    offenders: list[str] = []
    pattern = re.compile(r"datetime\.(?:utcnow\(\)|utcfromtimestamp\()")
    for path in sorted((BACKEND / "app").rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(BACKEND)}:{number}: {line.strip()}")
    assert not offenders, "наивное UTC-время вернулось в код:\n" + "\n".join(offenders)


def test_utcnow_is_aware():
    assert utcnow().tzinfo is not None
