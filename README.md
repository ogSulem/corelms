# CoreLMS

[![CI](https://github.com/ogSulem/corelms/actions/workflows/ci.yml/badge.svg)](https://github.com/ogSulem/corelms/actions/workflows/ci.yml)

> License: **Proprietary**. This repository is provided for evaluation/demo purposes. For commercial use, a separate license agreement is required.

CoreLMS — система обучения и контроля квалификации сотрудников:

- обучение по модулям/урокам
- материалы уроков (S3-compatible storage)
- тестирование (квизы), прогресс, XP
- админ-панель: импорт контента, регенерация квизов, управление пользователями
- аудит безопасности (security audit log)

## Архитектура

- **Frontend**: Next.js + TypeScript
- **Backend**: FastAPI + SQLAlchemy + Alembic
- **DB**: Postgres
- **Queue**: Redis + RQ (импорт/реген/cleanup очереди)
- **Storage**: S3-compatible

## Быстрый старт (локально, Docker Compose)

1) Создай `.env` из шаблона:

```bash
cp .env.example .env
```

2) Запусти:

```bash
docker compose up --build
```

Открыть:

- UI: `http://localhost:3000`
- API: `http://localhost:8000`

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
