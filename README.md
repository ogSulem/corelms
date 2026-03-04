# CoreLMS

[![CI](https://github.com/ogSulem/corelms/actions/workflows/ci.yml/badge.svg)](https://github.com/ogSulem/corelms/actions/workflows/ci.yml)

> License: **Proprietary**. This repository is provided for evaluation/demo purposes. For commercial use, a separate license agreement is required.

CoreLMS — система обучения и контроля квалификации сотрудников:

- обучение по модулям/урокам
- материалы уроков (S3-compatible storage)
- тестирование (квизы), прогресс, XP
- админ-панель: импорт контента, регенерация квизов, управление пользователями
- аудит безопасности (security audit log)

## Состав репозитория

- **`frontend/`** — Next.js приложение (UI + server routes `/api/*`)
- **`backend/`** — FastAPI приложение (API, воркеры RQ, миграции Alembic)
- **`nginx/`** — локальный ingress (reverse proxy в docker-compose)
- **`docker-compose.yml`** — локальный запуск (nginx -> frontend -> backend)
- **`docker-compose.vps.yml`** — запуск на VPS (Caddy -> frontend/backend)
- **`.env.example`** — шаблон переменных окружения

## Архитектура

- **Frontend**: Next.js + TypeScript
- **Backend**: FastAPI + SQLAlchemy + Alembic
- **DB**: Postgres
- **Queue**: Redis + RQ (импорт/реген/cleanup очереди)
- **Storage**: S3-compatible

### Потоки запросов (вкратце)

- Браузер открывает UI по одному публичному origin (например `http://127.0.0.1:8080`).
- UI делает запросы к API по same-origin путям:
  - `GET /api/auth/*` — Next.js server routes (ставят httpOnly cookies)
  - `GET/POST /api/backend/*` — прокси в backend (cookies приклеиваются автоматически)
- Backend не публикуется наружу в локальном compose (доступен только внутри docker-сети).

## Быстрый старт (локально, Docker Compose)

Локальный запуск рассчитан на работу через **nginx** как единую точку входа.

1) Создай `.env` из шаблона:

```bash
cp .env.example .env
```

2) Выбери **один** origin и используй его всегда (это важно для cookie-сессии):

- `http://localhost:<PORT>` и `http://127.0.0.1:<PORT>` считаются **разными хостами**.
- Если залогинился на `localhost`, а потом открыл `127.0.0.1`, браузер **не отправит** host-only cookies (`core_token/core_refresh`) и будет выглядеть как “разлогин”.

Это нормальное поведение браузера: cookies привязаны к домену.

Рекомендуем для локалки:

- `NGINX_HTTP_PORT=8080`
- `PUBLIC_APP_URL=http://127.0.0.1:8080`
- `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8080`
- `CORS_ALLOW_ORIGINS=http://127.0.0.1:8080`

Если хочешь **поддерживать оба** (`localhost` и `127.0.0.1`), это возможно для CORS:

- `CORS_ALLOW_ORIGINS=http://localhost:8080,http://127.0.0.1:8080`

Но cookies всё равно будут отдельные для каждого хоста.

3) Запусти:

```bash
docker compose up --build
```

Открыть:

- UI (через nginx): `http://127.0.0.1:${NGINX_HTTP_PORT:-80}`
- API из браузера: `http://127.0.0.1:${NGINX_HTTP_PORT:-80}/api/*`

По умолчанию `backend` и `frontend` не публикуют 8000/3000 на хост (они доступны внутри docker-сети). Наружу публикуется только `nginx`.

### Полезные команды

- Остановить:

```bash
docker compose down
```

- Пересобрать и поднять:

```bash
docker compose up -d --build
```

- Посмотреть логи:

```bash
docker compose logs -f --tail=200 nginx
docker compose logs -f --tail=200 backend
docker compose logs -f --tail=200 worker_import
```

### Первый вход / админ

При первом старте backend может автоматически создать администратора, если в БД ещё нет admin-пользователя:

- `BOOTSTRAP_ADMIN_NAME`
- `BOOTSTRAP_ADMIN_PASSWORD`

## Админ-панель (как пользоваться)

### Импорт контента

- Импорт ZIP ставится в очередь `corelms_import`.
- В админке видны:
  - текущая активная задача (started)
  - очередь (queued/deferred/scheduled)
  - история
- Можно отменять queued задачи (и best-effort отменять started через cancel checkpoints).

### Регенерация квизов (AI)

- Реген ставится в очередь `corelms_regen`.
- Статусы в UI опираются на RQ `status` (а не на `stage`), чтобы “Current” не пропадал при обновлениях.

### Пользователи: создание и сброс пароля

- При создании пользователя и при сбросе пароля админ получает **временный пароль**.
- UI показывает модалку с инструкцией и временным паролем.
- Пользователь при первом входе попадает на `/force-password-change`:
  - вводит текущий (временный) пароль
  - задаёт новый пароль + подтверждение
  - указывает номер телефона

## Переменные окружения (.env)

Шаблон: `.env.example`.

### Самые важные переменные

- **`APP_ENV`**
  - `development` — более мягкие defaults для локалки
  - `production` — строгие проверки (секреты/URL'ы), лучше для VPS
- **`PUBLIC_APP_URL`** — публичный origin фронта (то, что вводится в браузере)
- **`CORS_ALLOW_ORIGINS`** — список origin'ов для CORS (должен совпадать с тем, где открывают UI)
- **`NEXT_PUBLIC_API_BASE_URL`** — публичный origin для фронта (обычно равен `PUBLIC_APP_URL`)
- **`CORE_INTERNAL_API_BASE_URL`** — внутренний URL backend в docker-сети (обычно `http://backend:8000`)
- **`COOKIE_SECURE`**
  - `false` для HTTP (локалка, IP-only)
  - `true` для HTTPS (домен + TLS)

Минимальный набор для production:

- `APP_ENV=production`
- `JWT_SECRET_KEY` (сильный)
- `ALLOW_PUBLIC_REGISTER=false`
- `PUBLIC_APP_URL` (URL фронта)
- `CORS_ALLOW_ORIGINS` (URL фронта)

Storage:

- для внешнего S3 укажи `S3_ENDPOINT_URL` / `S3_PUBLIC_ENDPOINT_URL` и ключи
- приложение рассчитано на внешний S3 (например REG.RU)

## Healthchecks

- `GET /health/live`
- `GET /health/ready`

## Тесты

```bash
python -m pytest -q
```

## Деплой на VPS (как сайт)

В репозитории есть отдельная схема для VPS:

- `docker-compose.vps.yml`
- `Caddyfile`

Принцип:

- наружу открыты только **80/443** (reverse proxy)
- Postgres/Redis/backend/frontend/workers работают внутри docker-сети

### Запуск

1) На VPS создай `.env` (из `.env.example`).

2) Запусти:

```bash
docker compose -f docker-compose.vps.yml up --build -d
```

Открыть:

- сайт: `http://<VPS_IP>/`
- API: `http://<VPS_IP>/api/`

### HTTPS

Сейчас `Caddyfile` настроен для работы по IP (HTTP на 80).
Когда появится домен — включи HTTPS в Caddy и укажи домен в `PUBLIC_APP_URL`/`CORS_ALLOW_ORIGINS`.

## Перенос данных (локально -> VPS)

### Postgres (рекомендуемый способ)

Локально:

```bash
docker compose exec -T postgres pg_dump -U sdlp -d sdlp -Fc > backup.dump
```

На VPS:

```bash
cat backup.dump | docker compose -f docker-compose.vps.yml exec -T postgres pg_restore -U sdlp -d sdlp --clean --if-exists
```

### Контент (S3)

- Если используешь внешний S3 (REG.RU/AWS/etc) — контент не нужно переносить, он уже в бакете.
- Если локально контент был в другом хранилище — перенеси его в S3 заранее (любым S3-клиентом).

## Troubleshooting

- **Очередь “не исполняется”**: проверь workers для нужной очереди (`WORKERS: 0` в UI) и что контейнеры `worker_import`/`worker_regen` запущены.
- **CORS ошибки**: выставь `CORS_ALLOW_ORIGINS` ровно на URL фронта.
- **Force password change**: убедись, что пользователь реально имеет `must_change_password=true` и что фронт редиректит на `/force-password-change`.

### Частый случай: “после перезагрузки выкинуло”

Проверь:

- что ты не сменил `localhost` на `127.0.0.1` (или наоборот)
- что `COOKIE_SECURE=false` при HTTP
- что refresh не инвалидируется (после `down -v` он станет невалидным)

### Важно про `docker compose down -v`

`docker compose down -v` удаляет volumes Postgres/Redis.

- Данные БД удалятся.
- Все refresh-сессии в Redis потеряются.

После этого нужно:

- заново поднять compose
- заново залогиниться (старые cookies станут невалидными)

---

## Примечания по безопасности

- Никогда не коммить `.env` с реальными ключами.
- В production обязательно замени:
  - `JWT_SECRET_KEY`
  - `BOOTSTRAP_ADMIN_PASSWORD`
  - ключи S3
