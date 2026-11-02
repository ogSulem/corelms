#!/usr/bin/env python3
"""Проверка docker-compose.yml до деплоя.

Зачем: дубликат ключа (`environment:` два раза в одной службе) ломает
`docker compose up` сообщением

    failed to parse docker-compose.yml: yaml: construct errors:
      line 1: line 220: mapping key "environment" already defined at line 208

и выясняется это уже после десятиминутной сборки образов. PyYAML по умолчанию
молча оставляет последнее значение, а Docker Compose (Go YAML) падает — поэтому
здесь свой загрузчик, который тоже падает, но за секунду и с понятным текстом.

Запуск:  python3 deploy/check-compose.py [docker-compose.yml]
Код 1 — файл невалиден, код 0 — всё в порядке (если docker есть, дополнительно
запускается `docker compose config -q`).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML есть в backend-зависимостях
    yaml = None


class DuplicateKeyError(ValueError):
    pass


def _strict_loader():
    class StrictLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader, node, deep=False):
        seen = {}
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if not isinstance(key, (str, int, float, bool, type(None))):
                continue
            if key in seen:
                raise DuplicateKeyError(
                    f"дубликат ключа {key!r}: строка {key_node.start_mark.line + 1} "
                    f"и строка {seen[key] + 1}"
                )
            seen[key] = key_node.start_mark.line
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    StrictLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping
    )
    return StrictLoader


def check_env_entries(service: str, environment) -> list[str]:
    """Одинаковые имена в одном списке окружения — тоже ошибка (побеждает последний)."""
    if not isinstance(environment, list):
        return []
    seen: set[str] = set()
    problems: list[str] = []
    for item in environment:
        name = str(item or "").split("=", 1)[0].strip()
        if not name or name in seen:
            if name:
                problems.append(f"служба {service}: переменная {name} указана дважды")
            continue
        seen.add(name)
    return problems


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "docker-compose.yml")
    if not path.is_file():
        print(f"нет файла {path}")
        return 1
    text = path.read_text(encoding="utf-8")

    problems: list[str] = []
    data = None
    if yaml is None:
        print("PyYAML не установлен — без него проверю только `docker compose config`")
    else:
        try:
            data = yaml.load(text, Loader=_strict_loader())  # noqa: S506 - SafeLoader
        except DuplicateKeyError as exc:
            problems.append(str(exc))
        except yaml.YAMLError as exc:
            problems.append(f"YAML не разбирается: {exc}")

    services = (data or {}).get("services") if isinstance(data, dict) else None
    if isinstance(services, dict):
        for name, service in services.items():
            if not isinstance(service, dict):
                problems.append(f"служба {name}: ожидался объект")
                continue
            if "build" not in service and "image" not in service:
                problems.append(f"служба {name}: нет ни build, ни image")
            problems.extend(check_env_entries(name, service.get("environment")))
            depends = service.get("depends_on")
            names = list(depends) if isinstance(depends, dict) else list(depends or [])
            for dependency in names:
                if dependency not in services:
                    problems.append(f"служба {name}: depends_on ссылается на несуществующую {dependency}")
                elif isinstance(depends, dict):
                    entry = depends.get(dependency)
                    condition = entry.get("condition") if isinstance(entry, dict) else None
                    if condition and condition not in {"service_started", "service_healthy", "service_completed_successfully"}:
                        problems.append(f"служба {name}: недопустимое условие depends_on {condition!r}")
            if "ports" in service and not isinstance(service["ports"], list):
                problems.append(f"служба {name}: ports должен быть списком")
        required = {"backend", "frontend", "worker", "worker_media", "postgres", "redis"}
        missing = sorted(required - set(services))
        if missing:
            problems.append("нет служб: " + ", ".join(missing))

    if problems:
        print(f"{path}: найдены ошибки, деплой остановлен:")
        for item in problems:
            print(f"  - {item}")
        return 1

    # Настоящий парсер Docker Compose: на сервере он и есть основная проверка,
    # потому что PyYAML там может отсутствовать.
    if shutil.which("docker") and os.environ.get("SKIP_DOCKER_COMPOSE_CONFIG") != "1":
        env_file = path.parent / ".env"
        created = False
        if not env_file.exists():
            env_file.write_text("", encoding="utf-8")
            created = True
        try:
            result = subprocess.run(
                ["docker", "compose", "-f", str(path), "config", "-q"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            result = None
            print(f"docker compose недоступен: {exc}")
        finally:
            if created:
                env_file.unlink(missing_ok=True)
        if result is not None and result.returncode != 0:
            print(f"{path}: docker compose config не принял файл:")
            print((result.stderr or result.stdout).strip())
            return 1

    if yaml is None and not shutil.which("docker"):
        print(f"{path}: проверить нечем — нет ни PyYAML, ни docker compose")
        return 0
    print(f"{path}: структура в порядке")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
