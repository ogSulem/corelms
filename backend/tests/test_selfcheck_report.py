"""Самопроверка (`scripts/selfcheck.py`) должна видеть все очереди и память Redis.

Это скрипт, который запускают на сервере без SSH-доступа к интерфейсу; если он
показывает «очередь default: 0», зависший импорт медиа выглядит как норма.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest


@pytest.fixture(scope="module")
def selfcheck():
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "selfcheck.py"
    spec = importlib.util.spec_from_file_location("corelms_selfcheck", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["corelms_selfcheck"] = module
    spec.loader.exec_module(module)
    return module


def test_infrastructure_report_lists_every_configured_queue(selfcheck, redis_memory):
    from app.core.config import settings

    lines, _problems = selfcheck.infrastructure_report()
    text = "\n".join(lines)
    for key in ("import", "regen", "cleanup", "media"):
        name = str(getattr(settings, f"rq_queue_{key}", "") or "").strip()
        if name:
            assert f"очередь {name}" in text, f"нет строки про очередь {name}"


def test_infrastructure_report_warns_before_redis_is_full(selfcheck, monkeypatch):
    class FullRedis:
        def ping(self):
            return True

        def llen(self, name):
            return 0

        def info(self, section=None):
            return {"used_memory": 250 * 1024 * 1024, "maxmemory": 256 * 1024 * 1024}

    monkeypatch.setattr(selfcheck, "get_redis", lambda: FullRedis(), raising=False)
    import app.core.redis_client as redis_client

    monkeypatch.setattr(redis_client, "get_redis", lambda: FullRedis())
    lines, problems = selfcheck.infrastructure_report()
    assert any("память Redis" in line for line in lines)
    assert any("Redis заполнен" in problem for problem in problems)


def test_infrastructure_report_checks_the_effective_bucket(selfcheck, client, admin_headers, storage):
    response = client.put("/admin/settings/storage", headers=admin_headers,
                          json={"s3_bucket": "selfcheck-bucket", "s3_endpoint_url": "https://s3.example.test"})
    assert response.status_code == 200, response.text
    storage.buckets.clear()
    lines, _problems = selfcheck.infrastructure_report()
    assert any("S3 bucket" in line for line in lines)
    assert storage.buckets == ["selfcheck-bucket"]
