# CoreLMS

[![CI](https://github.com/ogSulem/corelms/actions/workflows/ci.yml/badge.svg)](https://github.com/ogSulem/corelms/actions/workflows/ci.yml)

CoreLMS — внутренняя LMS для обучения и контроля квалификации сотрудников.

Основные возможности:

- обучение по модулям/урокам
- материалы уроков в S3-совместимом хранилище
- тестирование (квизы), прогресс, XP
- админ-панель: импорт контента, регенерация квизов, управление пользователями
- аудит безопасности (security audit log)

Лицензия:

- репозиторий предоставляется для демонстрации/оценки
- для коммерческого использования нужен отдельный договор

---

## Состав репозитория

- **`frontend/`** — Next.js (UI + server routes `/api/*`)
- **`backend/`** — FastAPI (API + воркеры RQ + Alembic)
- **`nginx/`** — ingress для режима IP-only
- **`Caddyfile`** — ingress для режима домен+TLS (профиль `tls`)
- **`docker-compose.yml`** — единый способ запуска (локально/VPS)
- **`.env.example`** — минимальный шаблон запуска (без тюнинга)

---

## Как устроено (коротко)

### Один origin — это важно

Приложение рассчитано на **один публичный origin** (то, что вводят в браузере).

- `http://localhost:8080` и `http://127.0.0.1:8080` — **разные хосты**.
- Cookies `core_token/core_refresh` — host-only (если не задан `COOKIE_DOMAIN`).
- Поэтому “залогонился на localhost, открыл 127.0.0.1 — разлогинило” это нормально.

### Поток запросов

- Браузер открывает UI на `PUBLIC_APP_URL`.
- UI делает запросы по same-origin:
  - `/api/auth/*` — Next.js server routes (ставят/чистят httpOnly cookies)
  - `/api/backend/*` — прокси в backend (с учётом cookies)
- Backend не должен быть доступен напрямую из интернета: он доступен только внутри docker-сети.

---

## Быстрый старт (локально)

1) Создай `.env`:

```bash
cp .env.example .env
```

2) Рекомендуемые значения для локалки:

- `NGINX_HTTP_PORT=8080`
- `PUBLIC_APP_URL=http://127.0.0.1:8080`
- `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8080`
- `CORS_ALLOW_ORIGINS=http://127.0.0.1:8080`
- `COOKIE_SECURE=false`

3) Запусти:

```bash
docker compose up --build
```

Открыть:

- UI: `http://127.0.0.1:8080/`
- API: `http://127.0.0.1:8080/api/*`

### Отладочный профиль (прямой доступ к портам)

Если нужно опубликовать `backend:8000`, `frontend:3000`, `postgres:5432`, `redis:6379` только на `127.0.0.1`, используй:

```bash
docker compose --profile dev up -d --build
```

---

## Деплой на VPS (production)

Здесь описано два режима:

- **Режим 1: VPS IP-only (HTTP)** — nginx на произвольном порту (например `:8888`)
- **Режим 2: VPS домен + TLS (HTTPS)** — Caddy на `:80/:443` (профиль `tls`)

### Базовый принцип безопасности

- наружу публикуется только ingress (nginx или caddy)
- `backend`, `postgres`, `redis`, воркеры — только внутри docker-сети

### Шаги (общие)

1) На VPS создай `.env` из `.env.example`

2) Обязательно замени секреты:

- `JWT_SECRET_KEY`
- `BOOTSTRAP_ADMIN_PASSWORD`
- `POSTGRES_PASSWORD`
- `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY`

3) Проверь, что `ALLOW_PUBLIC_REGISTER=false`.

---

### Режим 1: VPS IP-only (HTTP через nginx)

Настройки:

- `NGINX_HTTP_PORT=8888` (или любой свободный)
- `PUBLIC_APP_URL=http://<VPS_IP>:8888`
- `NEXT_PUBLIC_API_BASE_URL=http://<VPS_IP>:8888`
- `CORS_ALLOW_ORIGINS=http://<VPS_IP>:8888`
- `COOKIE_SECURE=false`

Запуск:

```bash
docker compose up -d --build
```

Проверка:

- UI: `http://<VPS_IP>:8888/`
- API: `http://<VPS_IP>:8888/api/health/ready`

---

### Режим 2: VPS домен + TLS (HTTPS через Caddy)

Настройки:

- `CADDY_DOMAIN=lms.example.com`
- `CADDY_EMAIL=you@example.com`
- `PUBLIC_APP_URL=https://lms.example.com`
- `NEXT_PUBLIC_API_BASE_URL=https://lms.example.com`
- `CORS_ALLOW_ORIGINS=https://lms.example.com`
- `COOKIE_SECURE=true`

Запуск:

```bash
docker compose --profile tls up -d --build
```

---

## Первый админ

На пустой БД backend может создать первого администратора, если в системе ещё нет admin-пользователя:

- `BOOTSTRAP_ADMIN_NAME`
- `BOOTSTRAP_ADMIN_PASSWORD`

Рекомендация для production:

- после первого входа создай второго админа
- затем поменяй пароль и выключи bootstrap (оставь переменные пустыми)

---

## Healthchecks

- `GET /api/health/live`
- `GET /api/health/ready`

Переключатель строгости readiness:

- `HEALTH_READY_CHECK_S3=true` — readiness требует доступность S3
- `HEALTH_READY_CHECK_S3=false` — readiness по DB+Redis (устойчивее при нестабильном S3)

---

## Эксплуатация: полезные команды

- Остановить:

```bash
docker compose down
```

- Логи:

```bash
docker compose logs -f --tail=200 nginx
docker compose logs -f --tail=200 backend
docker compose logs -f --tail=200 worker_import
docker compose logs -f --tail=200 worker_regen
```

---

## Перенос данных (локально -> VPS)

### Postgres

Локально:

```bash
docker compose exec -T postgres pg_dump -U sdlp -d sdlp -Fc > backup.dump
```

На VPS:

```bash
cat backup.dump | docker compose exec -T postgres pg_restore -U sdlp -d sdlp --clean --if-exists
```

### Контент (S3)

- если используешь внешний S3 — контент уже в бакете, переносить нечего
- если контент был локально — перенеси в S3 заранее любым S3-клиентом

---

## Troubleshooting

### Частый случай: “после перезагрузки выкинуло”

Проверь:

- не поменял ли ты `localhost` на `127.0.0.1` (или наоборот)
- при HTTP должен быть `COOKIE_SECURE=false`
- после `docker compose down -v` Redis очищается, refresh-сессии становятся невалидными

### Очереди не исполняются

- открой админку, вкладка diagnostics/jobs: `WORKERS: 0` значит воркеры не поднялись
- проверь контейнеры `worker_import`, `worker_regen`, `worker_default`
- проверь `REDIS_URL`

### CORS ошибки

- `CORS_ALLOW_ORIGINS` должен точно совпадать с `PUBLIC_APP_URL` (origin в браузере)

---

## Advanced: опциональные переменные окружения

`.env.example` специально минимальный. Ниже — опциональные настройки из `backend/app/core/config.py`.

### OpenRouter (если нужен AI)

- `OPENROUTER_ENABLED=true`
- `OPENROUTER_API_KEY=...`

Опционально:

- `OPENROUTER_BASE_URL`
- `OPENROUTER_MODEL`
- `OPENROUTER_TIMEOUT_CONNECT`
- `OPENROUTER_TIMEOUT_READ`
- `OPENROUTER_TIMEOUT_WRITE`
- `OPENROUTER_TEMPERATURE`
- `OPENROUTER_HTTP_REFERER`
- `OPENROUTER_APP_TITLE`
- `LLM_PROVIDER_ORDER`

### LLM debug (диагностика генерации квизов)

По умолчанию debug выключен.

- `LLM_DEBUG_SAVE=true` — сохранять диагностические срезы в meta RQ job (видно в админке)
- `LLM_DEBUG_LOG=true` — писать эти срезы в логи worker
- `LLM_DEBUG_MAX_CHARS=2000` — лимит на размер сниппетов

Важно: при включении debug может содержать фрагменты текста уроков и вывода модели.

### S3 тюнинг (таймауты, presign TTL и т.д.)

- `S3_REGION_NAME`
- `S3_ADDRESSING_STYLE`
- `S3_PRESIGN_DOWNLOAD_EXPIRES_SECONDS`
- `S3_PRESIGN_UPLOAD_EXPIRES_SECONDS`
- `S3_PRESIGN_MULTIPART_PART_EXPIRES_SECONDS`
- `S3_CONNECT_TIMEOUT_SECONDS`
- `S3_READ_TIMEOUT_SECONDS`
- `S3_MAX_ATTEMPTS`
- `S3_MAX_POOL_CONNECTIONS`

### Uploads cleanup (операционные лимиты)

- `UPLOADS_ADMIN_TTL_HOURS`
- `UPLOADS_ADMIN_CLEANUP_INTERVAL_MINUTES`
- `UPLOADS_ADMIN_MULTIPART_TTL_HOURS`
- `UPLOADS_ADMIN_MULTIPART_MAX_ABORT`

---

## Примечания по безопасности

- никогда не коммить `.env`
- не включай runtime overrides в production без нужды:
  - `ALLOW_RUNTIME_LLM_OVERRIDES=false`
  - `ALLOW_RUNTIME_S3_OVERRIDES=false`
