# CoreLMS

[![CI](https://github.com/ogSulem/corelms/actions/workflows/ci.yml/badge.svg)](https://github.com/ogSulem/corelms/actions/workflows/ci.yml)

CoreLMS — внутренняя LMS для обучения и контроля квалификации сотрудников.

Основные возможности:

- обучение по модулям/урокам
- материалы уроков в S3-совместимом хранилище
- тестирование (квизы), прогресс, XP
- единый редактор уроков, файлов, проверяемых AI-черновиков тестов и доступа; управление пользователями
- аудит безопасности (security audit log)

## Управление материалами без потери прогресса

Новый редактор: **Админ-центр → Модули → Редактировать**. Можно добавлять файлы без переимпорта, заменять и перемещать их, восстанавливать версии, архивировать материалы и обновлять существующий модуль из ZIP. Заработанное прохождение отделено от изучения новых материалов. Excel просматривается внутри LMS без внешнего Office iframe; для пересчёта формул скачивается оригинал.

Материал, конспект и файлы переключаются вкладками. Тесты, основной файл, предпросмотр и аудитория настраиваются в одном редакторе. «Продажи» разделены на Google Sheets с последней успешной копией и версионируемую S3-библиотеку. Отдельный `worker_media` автоматически готовит MP4 для видео и PDF для DOCX/PPTX, не меняя оригиналы.

Ручной текст защищён от ZIP-замены, у текста и файлов есть история версий. Дашборд ведёт к фактическому следующему шагу; обновления материалов отмечаются отдельно от полученного зачёта.

**Существующую установку нужно обновить до миграции `0024` с резервной копией. Перед первым пересозданием Redis перенесите его данные в новый persistent-том `redis_data`: теперь используются AOF и `noeviction`, а не вытеснение сессий и задач. Не запускайте `up` поверх старой установки без подготовки.**

→ [Возможности, ограничения, безопасное внедрение и проверки](docs/content-lifecycle.md)

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

## Обновление и миграции

Актуальная версия схемы: **`0024`**. Миграция `0024` добавляет таблицу `app_settings` для настроек, которые администратор меняет в интерфейсе (токен AI и доступ к Google Sheets). Секреты в ней шифруются.

Применяйте миграции **явным отдельным шагом**, а не «на глаз» при первом `up`:

```bash
# 0) Сначала резервная копия (обязательно)
mkdir -p backups
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/pre-0024.dump

# 1) Какая версия сейчас и какая ожидается
docker compose run --rm --no-deps --entrypoint alembic backend current
docker compose run --rm --no-deps --entrypoint alembic backend heads

# 2) Собрать API, frontend и все воркеры из одной версии кода
docker compose build backend frontend worker_import worker_regen worker_default worker_media

# 3) Остановить писателей и применить схему
docker compose stop backend worker_import worker_regen worker_default worker_media
docker compose run --rm --no-deps --entrypoint alembic backend upgrade head

# 4) Запустить всё
docker compose up -d backend worker_import worker_regen worker_default worker_media frontend
```

Проверка после обновления:

```bash
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select version_num from alembic_version;"'
# ожидается 0024
curl -fsS http://127.0.0.1:8080/api/health/ready
```

Если API уже работает и обновлять контейнеры не нужно, достаточно:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current   # ожидается 0024 (head)
```

(У `docker compose run ... --entrypoint alembic` тот же результат для остановленного стека.)

Затем откройте **Админ-центр → Настройки**: блок «Сервер и схема данных» показывает текущую версию схемы. Если там `0024 / ожидается 0024`, миграция применена.

Альтернатива: `AUTO_MIGRATE_ON_START=true` заставляет API применить `upgrade head` при старте (с advisory-lock). Для controlled-обновления это менее прозрачно: сначала всё равно сделайте backup и обновите API/воркеры согласованно. В `docker-compose.yml` у воркеров этот флаг принудительно `false`.

Откат: восстановите согласованный backup PostgreSQL вместе с прежней версией приложения. `alembic downgrade` не является безопасным production-откатом после появления новых данных.

Если миграция сообщает, что объект уже существует, не удаляйте данные: проверьте `alembic current`, журналы и восстановите backup/согласуйте схему вручную.

---

## Настройки в интерфейсе

**Админ-центр → Настройки** (`/admin/settings`):

- **AI для тестов** — токен OpenRouter (или совместимого API), модель, адрес API, проверка подключения. Токен хранится в БД в зашифрованном виде и имеет приоритет над `OPENROUTER_*` из `.env`; воркеры видят его без перезапуска. Кнопка «Сбросить к серверу» возвращает значения окружения.
- **Google Sheets для «Продаж»** — идентификатор таблицы, JSON сервисного аккаунта или API key, проверка чтения листов. Доступно супер-администратору. Файлы продаж в S3 работают и без таблицы.
- **Хранилище файлов (S3)** — bucket, адрес API, публичный адрес, регион, ключи и проверка доступности bucket. Значения действуют сразу (хранятся как оверрайд поверх `.env`), «Сбросить к серверу» возвращает значения окружения. В production запись включается флагом `ALLOW_RUNTIME_S3_OVERRIDES=true`.
- **Сервер и схема** — окружение, публичный URL, лимит файла, bucket, версия схемы, состояние фоновых воркеров.

Отдельных форм настройки AI и S3 на экране «Диагностика» больше нет — там состояние сервисов и проверки целостности, а все изменения ведутся на `/admin/settings` (разделы «AI для тестов», «Продажи (Sheets)», «Хранилище файлов», «Сервер и схема»).

Ключ шифрования: `SETTINGS_ENCRYPTION_KEY`, иначе используется `JWT_SECRET_KEY`. Если ключ изменился, сохранённые токены перестают читаться — интерфейс попросит ввести их заново.

### Как генерируются тесты

1. В редакторе модуля откройте вкладку «Тесты» и выберите урок.
2. AI получает текст урока, документ (PDF/DOCX/PPTX) или вставленный фрагмент (до 12 000 символов) и возвращает **черновик** вопросов с вариантами и пояснениями. Сканы без текстового слоя и видео автоматически не распознаются.
3. Черновик не публикуется сам: проверьте вопросы и сохраните тест кнопкой «Сохранить тест».
4. «Подготовить тесты для всех уроков» создаёт черновики пачкой (до 50 уроков), только для уроков без вопросов или для всех.
5. Без токена AI тесты создаются вручную; обучение, файлы и прогресс от AI не зависят.

Для фоновой генерации должен работать воркер `worker_regen` с очередью `corelms_regen`.

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
- `docker compose down -v` удаляет persistent-тома, включая БД и Redis; не используйте эту команду для обычного обновления. Обычный `down` не удаляет тома. Без авторитетной Redis-сессии доступ и refresh не принимаются

### Очереди не исполняются

- открой админку, вкладка diagnostics/jobs: `WORKERS: 0` значит воркеры не поднялись
- проверь контейнеры `worker_import`, `worker_regen`, `worker_default`, `worker_media`
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

### Хранение исходников и версий

После `0021`/`0022` физическая TTL-очистка файлов/ZIP работает только как диагностика: данные не удаляются по неполному снимку ссылок. Архивирование выполняется в редакторе. Не включайте внешнюю S3 Lifecycle expiration для материалов и их версий; запланируйте объём хранения и отдельную политику retention.

Операционные настройки диагностики и незавершённых multipart-загрузок:

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


## Проверки разработки

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements-test.txt ruff
.venv/bin/pytest backend/tests
.venv/bin/ruff check backend --select F821,F823
cd frontend
yarn install --frozen-lockfile
yarn test && yarn typecheck && yarn lint && yarn build
```

SQLite не проверяет блокировки PostgreSQL. Миграции, реальные Redis-транзакции, конкурентная смена пароля и браузерные сценарии включаются отдельно — команды и предостережения в [руководстве](docs/content-lifecycle.md#проверки-и-воспроизведение). Не запускайте разрушительные тестовые фикстуры на рабочей БД. Перед `yarn build` остановите dev-сервер, если он использует тот же каталог `.next`.
