#!/usr/bin/env python
"""Самопроверка работающего стека изнутри контейнера backend.

Запуск на сервере (ничего не меняет в данных):

    docker compose exec -T backend python scripts/selfcheck.py

Скрипт печатает:
  * окружение и схему БД (без секретов, пароли замаскированы);
  * согласованность домена: PUBLIC_APP_URL / CORS_ALLOW_ORIGINS / COOKIE_SECURE,
    включая сравнение кириллического домена с его punycode-формой;
  * состояние базы, Redis, очередей и S3;
  * каждый GET-эндпоинт приложения под реальным администратором: код ответа,
    время и полный traceback для любого 5xx.

Только чтение: POST/PUT/PATCH/DELETE не вызываются.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import traceback
import uuid
from typing import Any

SKIP_PATHS = {
    "/health/ready",  # зависит от внешнего S3, проверяется отдельно
    "/docs",
    "/redoc",
    "/openapi.json",
}

# Нечего проверять без реальных объектов или специальных прав.
SKIP_PREFIXES = (
    "/assets/",
    "/quickstart/",
    "/events",
)

# Бесконечные SSE-потоки: запрос не завершится никогда, это норма.
SKIP_SUFFIXES = (
    "/events",
)


def _mask(value: str) -> str:
    if not value:
        return "—"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]}"


def _mask_url(value: str) -> str:
    """Скрыть пароль в connection string."""
    try:
        scheme, rest = value.split("://", 1)
    except ValueError:
        return _mask(value)
    if "@" not in rest:
        return value
    creds, tail = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{tail}"


def _origin_variants(origin: str) -> set[str]:
    """Один и тот же адрес в punycode и в юникоде — это один источник."""
    variants = {origin}
    try:
        scheme, host = origin.split("://", 1)
    except ValueError:
        return variants
    variants.add(f"{scheme}://{host.lower()}")
    try:
        variants.add(f"{scheme}://{host.encode('idna').decode()}")
        variants.add(f"{scheme}://{host.encode('idna').decode().lower()}")
    except (UnicodeError, UnicodeDecodeError):
        pass
    try:
        variants.add(f"{scheme}://{host.encode('ascii').decode('idna')}")
    except (UnicodeError, UnicodeDecodeError):
        pass
    return variants


def _env_flag(name: str) -> str:
    """Значение переменной окружения как есть (для кук она живёт во frontend)."""
    import os

    raw = os.environ.get(name)
    return "не задана" if raw is None or raw == "" else raw


def environment_report(db) -> tuple[list[str], list[str]]:
    """Возвращает (строки отчёта, найденные проблемы)."""
    from sqlalchemy import text

    from app.core.config import settings

    lines: list[str] = []
    problems: list[str] = []

    def add(title: str, value: Any, flag: str | None = None) -> None:
        lines.append(f"  {title:<26} {value}")
        if flag:
            problems.append(flag)

    lines.append("ОКРУЖЕНИЕ")
    add("APP_ENV", settings.app_env or "—", None if settings.app_env else "APP_ENV не задан")
    add("PUBLIC_APP_URL", settings.public_app_url or "—", None if settings.public_app_url else "PUBLIC_APP_URL не задан")
    add("DATABASE_URL", _mask_url(settings.database_url))
    add("REDIS_URL", _mask_url(settings.redis_url))
    add("JWT_SECRET_KEY", f"{len(settings.jwt_secret_key or '')} символов")
    add("COOKIE_SECURE", _env_flag("COOKIE_SECURE"))
    add("COOKIE_DOMAIN", _env_flag("COOKIE_DOMAIN"))
    add("S3 bucket", settings.s3_bucket or "—")
    add("S3 endpoint", settings.s3_endpoint_url or "—")
    add("AUTO_MIGRATE_ON_START", settings.auto_migrate_on_start)
    add("AI включён", settings.openrouter_enabled)

    import logging

    log_level = logging.getLogger("corelms").getEffectiveLevel()
    add("Уровень журнала", logging.getLevelName(log_level))
    if log_level > logging.INFO:
        problems.append(
            "Журнал запросов выключен (уровень выше INFO): docker compose logs backend будет пустым, "
            "и причину ошибки не увидеть. Обычно это следствие AUTO_MIGRATE_ON_START=true + старой сборки."
        )

    # --- Домен, куки и CORS ------------------------------------------------
    lines.append("")
    lines.append("ДОМЕН, КУКИ И CORS")
    public = (settings.public_app_url or "").strip()
    origins = [o.strip() for o in str(settings.cors_allow_origins or "").split(",") if o.strip()]
    add("CORS_ALLOW_ORIGINS", ", ".join(origins) or "—", None if origins else "CORS_ALLOW_ORIGINS пуст: не-браузерные клиенты работать будут, браузер — нет")

    host = ""
    scheme = ""
    if public:
        try:
            scheme, host = public.split("://", 1)
            host = host.rstrip("/")
        except ValueError:
            problems.append("PUBLIC_APP_URL без схемы http:// или https://")

    puny = ""
    if host:
        try:
            puny = f"{scheme}://{host.encode('idna').decode()}"
        except (UnicodeError, UnicodeDecodeError):
            puny = public
        add("Домен (unicode)", public)
        if puny != public:
            add("Домен (punycode)", puny)
        if scheme == "http" and _env_flag("COOKIE_SECURE").strip().lower() in {"true", "1", "yes"}:
            problems.append("COOKIE_SECURE=true при PUBLIC_APP_URL по http — вход не заработает")

    allow_all: set[str] = set()
    for origin in origins:
        allow_all |= _origin_variants(origin.rstrip("/"))
    if host:
        same = _origin_variants(f"{scheme}://{host}")
        if origins and not (same & allow_all):
            problems.append(
                "CORS_ALLOW_ORIGINS не содержит текущий домен: браузерные POST/PUT/DELETE получат 403 invalid_origin"
            )
        if origins and not (allow_all & same):
            pass
        # Кука со своим доменом должна совпадать с доменом страницы.
        cookie_domain = _env_flag("COOKIE_DOMAIN").strip()
        if cookie_domain in {"", "не задана"}:
            cookie_domain = ""
        cookie_secure = _env_flag("COOKIE_SECURE").strip().lower()
        if scheme == "https" and cookie_secure in {"false", "0", "no"}:
            problems.append("Сайт по https, но COOKIE_SECURE=false: куки входа уходят без Secure")
        if cookie_domain:
            base = host.split(":", 1)[0]
            if cookie_domain.lstrip(".") not in base:
                problems.append(
                    f"COOKIE_DOMAIN={cookie_domain} не совпадает с доменом {base}: браузер не примет куки входа"
                )

    # --- Схема БД ----------------------------------------------------------
    lines.append("")
    lines.append("СХЕМА БД")
    try:
        current = db.execute(text("select version_num from alembic_version")).scalar()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        current = None
    add("Версия схемы", current or "не определена", None if current else "В alembic_version нет строки")

    from app.routers.settings import expected_schema_revision

    expected = expected_schema_revision()
    add("Ожидаемый head", expected)
    if current and expected and str(current) != str(expected):
        problems.append(f"Схема {current} не совпадает с кодом {expected}: нужен alembic upgrade head")

    try:
        from app.db.session import pool_snapshot

        pool = pool_snapshot()
        lines.append(f"  Пул соединений БД          занято {pool.get('checked_out', '?')} из {pool.get('size', '?')} "
                     f"(+{pool.get('max_overflow', '?')} запасных, ожидание {pool.get('timeout_seconds', '?')} c)")
        if int(pool.get("checked_out") or 0) >= int(pool.get("size") or 0) + int(pool.get("max_overflow") or 0):
            problems.append("Все соединения с БД заняты: похоже, какой-то запрос держит сессию слишком долго")
    except Exception:
        pass

    lines.append("")
    lines.append("ДАННЫЕ")
    def _count(sql: str) -> object:
        try:
            return db.execute(text(sql)).scalar()
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            return f"ошибка: {type(exc).__name__}"

    for label, sql in (
        ("пользователей", "select count(*) from users"),
        ("сотрудников", "select count(*) from users where role in ('employee','partner')"),
        ("администраторов", "select count(*) from users where role in ('admin','superadmin')"),
        ("Пользователей с ролью вне списка", "select count(*) from users where role::text not in ('employee','partner','admin','superadmin')"),
        ("модулей", "select count(*) from modules"),
        ("уроков", "select count(*) from submodules where is_archived = false"),
        ("файлов", "select count(*) from content_assets"),
        ("событий обучения", "select count(*) from learning_events"),
        ("попыток тестов", "select count(*) from quiz_attempts"),
        ("завершений модулей", "select count(*) from module_completions"),
    ):
        value = _count(sql)
        if isinstance(value, str) and value.startswith("ошибка:"):
            problems.append(f"Запрос «{label}» не выполнился: {value}")
        lines.append(f"  {label:<26} {value}")
        if label.startswith("Пользователей с ролью") and value:
            problems.append(f"{value} пользователей с неизвестной ролью — список и прогресс могут падать")

    return lines, problems


def system_report() -> tuple[list[str], list[str]]:
    """Диск и память: переполненный диск даёт 500 на всех записях."""
    import shutil

    lines = ["", "СИСТЕМА"]
    problems: list[str] = []
    for path in ("/", "/data"):
        try:
            usage = shutil.disk_usage(path)
        except Exception:
            continue
        free_gb = usage.free / 1024 ** 3
        total_gb = usage.total / 1024 ** 3
        used_pct = 100 * usage.used / usage.total if usage.total else 0
        lines.append(f"  диск {path:<20} свободно {free_gb:.1f} ГБ из {total_gb:.1f} ГБ ({used_pct:.0f}% занято)")
        if free_gb < 2:
            problems.append(f"На разделе {path} свободно {free_gb:.1f} ГБ: загрузки и запись в БД могут падать с 500")
    try:
        with open("/proc/loadavg", encoding="utf-8") as handle:
            load = handle.read().split()[:3]
        lines.append(f"  load average             {' '.join(load)}")
    except Exception:
        pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            info = dict(line.split(":", 1) for line in handle if ":" in line)
        available = int(info.get("MemAvailable", "0 kB").split()[0]) / 1024 ** 2
        lines.append(f"  память доступно         {available:.2f} ГБ")
        if available < 0.15:
            problems.append("В контейнере почти нет свободной памяти: возможны падения по OOM (502/500)")
    except Exception:
        pass
    return lines, problems


def infrastructure_report() -> tuple[list[str], list[str]]:
    from app.core.config import settings
    from app.core.redis_client import get_redis
    from app.services.storage import get_s3_client

    lines = ["", "СЕРВИСЫ"]
    problems: list[str] = []

    try:
        r = get_redis()
        r.ping()
        lines.append("  Redis                     отвечает")
        for queue in (settings.rq_queue_import, settings.rq_queue_regen, settings.rq_queue_media):
            try:
                lines.append(f"  очередь {queue:<16} {int(r.llen(queue))} задач")
            except Exception:
                lines.append(f"  очередь {queue:<16} не прочитать")
        try:
            from rq import Worker

            lines.append(f"  воркеров RQ               {len(Worker.all(connection=r))}")
        except Exception as exc:
            lines.append(f"  воркеров RQ               ошибка: {type(exc).__name__}")
    except Exception as exc:
        lines.append(f"  Redis                     НЕ отвечает: {type(exc).__name__}")
        problems.append("Redis недоступен: вход, очереди и rate limit работать не будут")

    try:
        get_s3_client().head_bucket(Bucket=settings.s3_bucket)
        lines.append("  S3 bucket                 доступен")
    except Exception as exc:
        lines.append(f"  S3 bucket                 НЕ доступен: {type(exc).__name__}")
        problems.append(f"S3 bucket {settings.s3_bucket} недоступен: файлы и предпросмотр не откроются")

    return lines, problems


def error_report(limit: int = 5) -> tuple[list[str], list[str]]:
    """Последние серверные ошибки из журнала, который виден в настройках."""
    from app.services import error_log

    items, path = error_log.read_recent(limit=limit)
    lines = ["", "ЖУРНАЛ ОШИБОК (последние)"]
    if not items:
        lines.append("  пусто — с момента запуска 5xx не было")
        return lines, []

    lines.append(f"  файл: {path}")
    problems: list[str] = []
    for item in items:
        lines.append(
            f"  {item.get('ts', '')}  {item.get('status')}  {item.get('method')} {item.get('path')}  "
            f"код={item.get('rid')}"
        )
        if item.get("error"):
            lines.append(f"      {item['error']}")
        tb = str(item.get("traceback") or "").strip().splitlines()
        if tb:
            lines.append(f"      {tb[-1].strip()}")
        if int(item.get("status") or 500) != 503:
            problems.append(f"Серверная ошибка {item.get('rid')}: {item.get('method')} {item.get('path')} → {item.get('status')}")
    return lines, problems


def _sample_ids(db) -> dict[str, str]:
    from sqlalchemy import select

    from app.models.asset import ContentAsset
    from app.models.module import Module, Submodule
    from app.models.quiz import Quiz
    from app.models.user import User

    ids = {
        "user_id": db.scalar(select(User.id).order_by(User.created_at)),
        "module_id": db.scalar(select(Module.id).order_by(Module.title)),
        "submodule_id": db.scalar(select(Submodule.id).order_by(Submodule.order)),
        "quiz_id": db.scalar(select(Quiz.id)),
        "asset_id": db.scalar(select(ContentAsset.id)),
        "tag_id": None,
    }
    try:
        from app.models.tag import Tag

        ids["tag_id"] = db.scalar(select(Tag.id))
    except Exception:
        ids["tag_id"] = None
    return {k: (str(v) if v else "00000000-0000-0000-0000-000000000000") for k, v in ids.items()}


def endpoint_report(client, admin_token: str, db) -> tuple[list[str], list[str], list[tuple[str, str]], list[str], list[str]]:
    app = client.app
    ids = _sample_ids(db)
    headers = {"Authorization": f"Bearer {admin_token}"}

    lines = ["", "ЭНДПОИНТЫ (GET, под администратором)"]
    password_blocked: list[str] = []
    degraded: list[str] = []
    failures: list[str] = []
    traces: list[tuple[str, str]] = []
    slow: list[str] = []

    seen: set[str] = set()
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if "GET" not in methods or path in SKIP_PATHS:
            continue
        if path.startswith(SKIP_PREFIXES) or path.endswith(SKIP_SUFFIXES):
            continue
        if "{" not in path and path.count("/") == 0:
            continue
        if "{" in path:
            if any(part not in ids for part in _placeholders(path)):
                continue
            url = path
            for key, value in ids.items():
                url = url.replace("{" + key + "}", value)
            if "{" in url:
                continue
        else:
            url = path
        if url in seen:
            continue
        seen.add(url)

        print(f"  … {url}", file=sys.stderr, flush=True)
        started = time.perf_counter()
        response, error = _timed_get(client, url, headers)
        elapsed = int((time.perf_counter() - started) * 1000)
        if response is None and error is None:
            lines.append(f"  ----  {url}  (таймаут {REQUEST_TIMEOUT_SECONDS} c)")
            failures.append(f"{url} → таймаут {REQUEST_TIMEOUT_SECONDS} c")
            continue
        try:
            if error is not None:
                raise error
            if response.status_code == 403 and "password_change_required" in response.text:
                lines.append(f"  403  {url}  (нужна смена пароля у проверяющего администратора)")
                password_blocked.append(url)
                continue
            if response.status_code == 503:
                body = response.text[:300].replace("\n", " ")
                lines.append(f"  503  {url}  ({elapsed} мс)  зависимость недоступна: {body}")
                degraded.append(f"{url} → 503: {body}")
            elif response.status_code >= 500:
                body = response.text[:400].replace("\n", " ")
                lines.append(f"  {response.status_code}  {url}  ({elapsed} мс)  {body}")
                failures.append(f"{url} → {response.status_code}")
            else:
                mark = "медленно" if elapsed > 5000 else ""
                lines.append(f"  {response.status_code}  {url}  ({elapsed} мс)  {mark}".rstrip())
                if elapsed > 5000:
                    slow.append(f"{url} — {elapsed} мс")
        except Exception:
            tb = traceback.format_exc()
            lines.append(f"  500  {url}  ({elapsed} мс)  исключение")
            failures.append(f"{url} → исключение")
            traces.append((url, tb))

    return lines, failures, traces, slow, password_blocked, degraded


REQUEST_TIMEOUT_SECONDS = 60


def _timed_get(client, url: str, headers: dict[str, str], timeout: float = REQUEST_TIMEOUT_SECONDS):
    """GET с жёстким пределом времени: зависший эндпоинт не должен вешать проверку."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["response"] = client.get(url, headers=headers)
        except BaseException as exc:  # noqa: BLE001 - покажем как есть
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return None, None
    return box.get("response"), box.get("error")


def _placeholders(path: str) -> list[str]:
    out = []
    for part in path.split("/"):
        if part.startswith("{") and part.endswith("}"):
            out.append(part[1:-1])
    return out


def _admin_token(db) -> tuple[str, str, str]:
    """Временная сессия администратора (ключи удаляются после проверки)."""
    from starlette.requests import Request

    from app.core.tokens import create_access_token
    from app.models.user import User, UserRole
    from app.services.auth_sessions import issue_session
    from sqlalchemy import select

    # Администратор с обязательной сменой пароля получает 403 на всё —
    # для проверки нужен тот, кто может работать.
    admins = list(db.scalars(select(User).where(User.role.in_([UserRole.superadmin, UserRole.admin])).order_by(User.created_at)))
    if not admins:
        raise SystemExit("В базе нет администратора: проверять эндпоинты не от кого")
    working = [a for a in admins if not getattr(a, "must_change_password", False)]
    if not working:
        raise SystemExit(
            "У всех администраторов включена смена пароля при входе (must_change_password). "
            "Пока пароль не сменён, админ-страницы отвечают 403 — войдите в интерфейс и смените пароль."
        )
    user = working[0]
    token, _, sid = issue_session(user, Request({"type": "http", "headers": [], "client": ("selfcheck", 0)}))
    return create_access_token(user, sid), str(user.id), sid


def main(client=None) -> int:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        env_lines, env_problems = environment_report(db)
        infra_lines, infra_problems = infrastructure_report()
        sys_lines, sys_problems = system_report()
        err_lines, err_problems = error_report()
        token, admin_id, admin_sid = _admin_token(db)

        if client is None:
            from fastapi.testclient import TestClient
            from app.main import create_app

            client = TestClient(create_app())

        ep_lines, failures, traces, slow, password_blocked, degraded = endpoint_report(client, token, db)
        _cleanup_session(admin_id, admin_sid)

        print("\n".join(env_lines))
        print("\n".join(sys_lines))
        print("\n".join(infra_lines))
        print("\n".join(err_lines))
        print("\n".join(ep_lines))

        problems = env_problems + sys_problems + infra_problems + err_problems
        print()
        if problems:
            print("НАЙДЕННЫЕ ПРОБЛЕМЫ НАСТРОЙКИ:")
            for item in problems:
                print(f"  - {item}")
        if slow:
            print("МЕДЛЕННЫЕ ЗАПРОСЫ (>5 c):")
            for item in slow:
                print(f"  - {item}")
        if degraded:
            print("ЗАВИСИМОСТИ НЕДОСТУПНЫ (503, страница работает в ограниченном виде):")
            for item in degraded:
                print(f"  - {item}")
        if password_blocked:
            print("ТРЕБУЕТСЯ СМЕНА ПАРОЛЯ (403):")
            for item in password_blocked:
                print(f"  - {item}")
        if failures:
            print("ОШИБКИ ЭНДПОИНТОВ:")
            for item in failures:
                print(f"  - {item}")
            for url, tb in traces:
                print()
                print(f"TRACEBACK {url}")
                print(tb)
        print()
        if failures:
            print(f"ИТОГ: {len(failures)} эндпоинтов с ошибкой, {len(problems)} проблем настройки")
            return 1
        print(f"ИТОГ: эндпоинты отвечают, проблем настройки: {len(problems)}")
        return 0 if not problems else 2
    finally:
        db.close()


def _cleanup_session(admin_id: str, sid: str) -> None:
    """Удалить временную сессию, чтобы не оставлять лишних ключей в Redis."""
    try:
        from app.core.redis_client import get_redis

        r = get_redis()
        r.delete(f"auth:session:{sid}")
        r.srem(f"auth:user_sessions:{admin_id}", sid)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
