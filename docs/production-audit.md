# Аудит production: окружение, развёртывание, TLS и приложение

Документ описывает, как проверить работающий сервер и что именно считается нормой.
Все команды безопасны: они ничего не пишут в базу, не удаляют тома и не пересоздают контейнеры.

## 1. Как этот проект поднимается

```
браузер → nginx:80 (по умолчанию) ─┐
        → caddy:80/443 (профиль tls)┴→ frontend:3000 (Next.js)
                                          ├→ /api/backend/*, /api/auth/* — свои route handlers
                                          └→ http://backend:8000 — FastAPI
```

* `nginx` — обычный HTTP-прокси на порт 80, стартует **всегда**.
* `caddy` — TLS-вход. Он описан с `profiles: ["tls"]`, поэтому запускается **только**
  командой `docker compose --profile tls up -d` (или через `COMPOSE_PROFILES=tls` в `.env`).
* И `nginx`, и `caddy` по умолчанию претендуют на порт 80. Одновременно они не поднимутся:
  нужно либо остановить `nginx` (`docker compose stop nginx`), либо дать ему другой порт
  (`NGINX_HTTP_PORT=8080` в `.env`).
* Сертификат Caddy получает сам по `CADDY_DOMAIN` из `.env` (ACME http-01 → порт 80 должен
  быть свободен и доступен из интернета). Отдельно выпускать сертификат не нужно.

## 2. Проверка окружения и TLS (без изменений в системе)

```bash
cd /opt/corelms
docker compose ps
grep -E '^(CADDY_DOMAIN|PUBLIC_APP_URL|CORS_ALLOW_ORIGINS|COOKIE_SECURE|COOKIE_DOMAIN|NEXT_PUBLIC_API_BASE_URL|CORE_INTERNAL_API_BASE_URL|AUTO_MIGRATE_ON_START|APP_ENV)=' .env
ss -lntp | grep -E ':80|:443'
curl -sSI https://edu.xn--80aaamzedb7cml.xn--p1ai/health/ready | head -5
curl -sSI http://edu.xn--80aaamzedb7cml.xn--p1ai/health/ready | head -3
```

Нормы:

| Что                                 | Норма                                                             |
| ----------------------------------- | ----------------------------------------------------------------- |
| `docker compose ps`                 | `postgres`, `redis`, `backend` — `healthy`; остальные `running`    |
| `CADDY_DOMAIN`                      | домен без схемы, например `edu.каркастайги.рф`                     |
| `PUBLIC_APP_URL`                    | `https://<домен>`                                                 |
| `CORS_ALLOW_ORIGINS`                | **тот же домен в punycode**: `https://edu.xn--80aaamzedb7cml.xn--p1ai` |
| `COOKIE_SECURE`                     | `true` (сайт по https)                                            |
| `COOKIE_DOMAIN`                     | пусто, либо ASCII-имя `edu.xn--80aaamzedb7cml.xn--p1ai`            |
| `AUTO_MIGRATE_ON_START`             | `false` (миграции применяются отдельной командой, см. п. 4)        |
| `curl -I https://…/health/ready`    | `HTTP/2 200`                                                      |
| `curl -I http://…/health/ready`     | `308` на https (если работает Caddy) или `200` (если сайт на nginx)|

Почему punycode: браузер всегда отправляет `Origin` в ASCII-форме
`https://edu.xn--80aaamzedb7cml.xn--p1ai`. Если в `CORS_ALLOW_ORIGINS` записан
кириллический домен, backend отвечает `403 invalid_origin` на каждый
POST/PUT/PATCH/DELETE, а `/api/auth/login` — «Недопустимый источник запроса».

`COOKIE_DOMAIN` с кириллицей frontend молча игнорирует (кука ставится без домена).
Это не ломает вход, но лучше держать там ASCII-форму или оставлять пусто.

## 3. Где искать источник «Ошибка сервера. Повторите попытку позже.»

Этот текст показывается, когда backend ответил 5xx с телом `internal server error`
или пустым телом. Backend пишет строку журнала на каждый запрос, включая статус и
`request_id`, поэтому источник находится точно:

```bash
docker compose logs backend --since 72h --no-log-prefix 2>/dev/null | grep -F '"status": 500' | tail -20
docker compose logs backend --since 72h --no-log-prefix 2>/dev/null | grep -c -F '"status": 500'
docker compose logs backend --since 72h --no-log-prefix 2>/dev/null | grep -F 'Traceback' -A 30 | tail -60
docker compose logs frontend --since 72h --no-log-prefix 2>/dev/null | grep -iE 'error|unhandled' | tail -30
```

В браузере: DevTools → Console, строка `[corelms] 500 … /admin/… request_id=…`.
По `request_id` из консоли находится traceback в логе backend:

```bash
docker compose logs backend --since 72h | grep -F '<request_id>' -A 40
```

## 4. Проверка развёртывания и схемы

```bash
docker compose images
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select version_num from alembic_version"'
docker compose exec -T backend python -c "import app.routers.settings as s; print(s.expected_schema_revision())"
docker compose exec -T backend python -m alembic current
df -h /var/lib/docker
free -m
```

Схема в базе обязана совпадать с `expected_schema_revision()`. Если версия ниже —
новый код обращается к колонкам, которых нет, и отвечает 500 на всех страницах.
Применять так (данные не удаляются, миграции только добавляют структуру):

```bash
docker compose exec -T backend python -m alembic upgrade head
```

## 5. Полная самопроверка приложения изнутри контейнера

Скрипт `backend/scripts/selfcheck.py` (попадает в образ через `COPY . .`):

```bash
docker compose exec -T backend python scripts/selfcheck.py
```

Что печатает: окружение (секреты замаскированы), согласованность домена/CORS/кук,
диск и память, версию схемы против head, счётчики данных, Redis/очереди/воркеры,
доступность S3, последние серверные ошибки из журнала и каждый GET-эндпоинт под
временным администратором — статус, время, текст ошибки и traceback. Временная сессия удаляется в конце. POST/PUT/DELETE не вызываются.

Код возврата: `0` — чисто, `1` — есть 5xx/исключения/таймауты, `2` — только замечания по настройке.

## 6. Журнал ошибок в интерфейсе (без SSH)

Backend пишет каждый ответ 5xx в файл на томе `backend_data`
(`/data/logs/errors.jsonl`, ротация по 2 МБ) вместе с `request_id`,
путём запроса и traceback. Администратор видит журнал в
**Админ-центр → Настройки → «Ошибки сервера»**, включая кнопку «Где именно упало».

Поэтому сообщение «Ошибка сервера… Код для поддержки: `<uuid>`» разбирается так:

1. открыть Настройки → «Ошибки сервера»;
2. найти строку с этим кодом;
3. раскрыть «Где именно упало» — там файл, строка и тип исключения.

Если интерфейс недоступен, то же самое из терминала:

```bash
docker compose exec -T backend tail -n 40 /data/logs/errors.jsonl
```

Или через API:

```bash
docker compose exec -T backend python -c "from app.services.error_log import read_recent; [print(i['ts'], i['status'], i['method'], i['path'], i['rid'], i.get('error','')) for i in read_recent(20)[0]]"
```

## 7. Обновление без потери данных

```bash
cd /opt/corelms
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > /srv/backups/pre-deploy-$(date +%F_%H-%M).dump
git fetch origin
git checkout main
git pull --ff-only
docker compose build backend frontend
docker compose up -d --no-deps backend frontend
docker compose ps
curl -sSI https://<домен>/health/ready | head -3
```

Никогда не использовать `docker compose down -v`, `docker volume rm pg_data`, `--renew-anon-volumes`:
Postgres живёт в томе `pg_data`, файлы — в S3, загрузки — в томе `backend_data`.
Redis хранит сессии и очереди — при пересоздании контейнера сессии пропадут (пользователи
просто войдут заново), но задачи в очередях лучше дождаться.
