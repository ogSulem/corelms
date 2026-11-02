"""docker-compose.yml должен разбираться так же строго, как его читает Docker.

Дубликат ключа (`environment:` дважды в одной службе) PyYAML молча
проглатывает, а Docker Compose падает:

    failed to parse docker-compose.yml: yaml: construct errors:
      line 1: line 220: mapping key "environment" already defined at line 208

Это и случилось на боевом сервере: образы собрались, а `compose up` отказался
поднимать контейнеры. Тест использует тот же проверяющий скрипт, что и деплой.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"


def _checker():
    path = ROOT / "deploy" / "check-compose.py"
    spec = importlib.util.spec_from_file_location("check_compose", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_compose_has_no_duplicate_keys():
    module = _checker()
    text = COMPOSE.read_text(encoding="utf-8")
    data = module.yaml.load(text, Loader=module._strict_loader())
    assert set(data["services"]) >= {"backend", "frontend", "worker", "worker_media", "postgres", "redis"}
    for name, service in data["services"].items():
        assert module.check_env_entries(name, service.get("environment")) == []


def test_compose_checker_rejects_duplicate_environment_block():
    module = _checker()
    broken = """
services:
  frontend:
    image: test
    environment:
      - A=1
    depends_on:
      backend:
        condition: service_started
    environment:
      - B=2
"""
    try:
        module.yaml.load(broken, Loader=module._strict_loader())
    except module.DuplicateKeyError as exc:
        assert "environment" in str(exc)
    else:  # pragma: no cover - страховка от молчаливого пропуска
        raise AssertionError("дубликат ключа не обнаружен")


def test_build_version_is_passed_to_app_containers():
    """Диагностика на форме входа показывает APP_VERSION: он должен доехать."""
    module = _checker()
    data = module.yaml.load(COMPOSE.read_text(encoding="utf-8"), Loader=module._strict_loader())
    for service in ("backend", "frontend"):
        entries = data["services"][service].get("environment") or []
        assert any(str(item).startswith("APP_VERSION=") for item in entries), service
