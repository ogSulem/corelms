# CoreLMS — Контроль квалификации

[![CI](https://github.com/ogSulem/SulemLMS/actions/workflows/ci.yml/badge.svg)](https://github.com/ogSulem/SulemLMS/actions/workflows/ci.yml)

> License: **Proprietary**. This repository is provided for evaluation/demo purposes. For commercial use, a separate license agreement is required.

Коммерчески‑готовая система контроля квалификации сотрудников: обучение, тестирование, прогресс, управление контентом и аудит безопасности.

Этот репозиторий предназначен для демонстрации продукта потенциальным владельцам/директорам компании и для быстрого развёртывания пилота.

- **One‑pager (для собственника/CEO)**: `docs/one-pager.md`
- **Demo‑script (10–15 минут)**: `docs/demo-script.md`

## Почему этому можно доверять (Proof)

- **Тесты**: быстрый прогон `pytest -q` (зелёный)
- **Security by default**:
  - принудительная смена пароля
  - запрет публичной регистрации в production
  - prod‑guards на секреты (fail‑fast)
- **Audit trail**: ключевые события безопасности и админ‑действия логируются (request_id + IP)
- **Ops‑готовность**: healthchecks + backup/restore инструкции

## Зачем это бизнесу

- **Единый контур квалификации**: обучение + проверка знаний + фиксация результата.
- **Прозрачность**: видно, кто прошёл уроки/тесты и где «проваливается» компетенция.
- **Управляемость**: админ создаёт пользователей, назначает обучение, управляет контентом.
- **Безопасность и расследуемость**: аудит ключевых действий + request_id + IP.

## Ключевые возможности

- **Пользователи**
  - роли: `admin` и `employee`
  - принудительная смена пароля при первом входе (`must_change_password`)
- **Контент и обучение**
  - модули, уроки (submodules), материалы (S3/MinIO)
  - линейный доступ (можно открывать следующий урок только после прохождения предыдущих)
- **Тестирование**
  - запуск теста, сессия теста, отправка ответов
  - попытки, результаты, XP/активность
- **Наблюдаемость / эксплуатация**
  - healthchecks: liveness/readiness
  - структурные request‑логи (JSON) с `request_id` и `user_id`
  - rate limiting на чувствительных эндпоинтах
- **Security audit log**
  - логируются: login/register/password change, админ‑действия (создание пользователей, сброс пароля, управление контентом, выдача presigned upload и т.д.)

## Демо

- **Короткое демо (GIF)**

![Demo](docs/screenshots/demo.gif)

- **Скриншоты**: `docs/screenshots/` (добавь свои изображения)

![Dashboard](docs/screenshots/dashboard.png)

![Module progress](docs/screenshots/module-progress.png)

![Quiz](docs/screenshots/quiz.png)

![Admin users](docs/screenshots/admin-users.png)

![Audit log](docs/screenshots/audit-log.png)

  - `docs/screenshots/dashboard.png`
  - `docs/screenshots/module-progress.png`
  - `docs/screenshots/quiz.png`
  - `docs/screenshots/admin-users.png`
  - `docs/screenshots/audit-log.png`

## Быстрый старт (Docker Compose)

1. Создай файл `backend/.env` на основе `backend/.env.example`.
2. Запусти:

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000

### Auth (cookie-only)

Фронт хранит JWT в HttpOnly cookie `core_token` (не доступно JavaScript).

Опционально можно задать TTL cookie (в секундах) для Next.js auth route handlers:

```bash
CORE_TOKEN_MAX_AGE_SECONDS=3600
```

## Архитектура (в двух словах)

- **Backend**: FastAPI + SQLAlchemy + Alembic
- **Frontend**: Next.js (React) + TypeScript
- **DB**: Postgres
- **Cache/limits/sessions**: Redis
- **Storage**: S3‑совместимое (MinIO)

## Тесты

```bash
python -m pytest -q
```

## Миграции

Миграции применяются автоматически при старте `backend` контейнера (см. `backend/scripts/entrypoint.sh`).

## Healthchecks

- `GET /health/live` — процесс жив
- `GET /health/ready` — зависимости (Postgres + Redis)

## Production заметки

- В production обязательно:
  - `APP_ENV=production`
  - `ALLOW_PUBLIC_REGISTER=false`
  - `JWT_SECRET_KEY` — сильный секрет

### Storage lifecycle (anti-bloat)

- `uploads/admin/*` — **временные** артефакты импорта (ZIP).
  - после успешного импорта ZIP удаляется автоматически.
  - при ошибке импорта ZIP удаляется best-effort.
  - дополнительно работает фоновая TTL‑уборка по префиксу `uploads/admin/`.
- `content/*` — **постоянный** контент (ассеты уроков).

Рекомендовано для production:
- настроить внешнее S3/объектное хранилище (AWS/Yandex/etc)
- закрыть публичный листинг бакетов
- выдавать доступ к ассетам через короткоживущие presigned URL

### IP / лицензирование (anti-theft)

- License: **Proprietary** (см. шапку README).
- Для пилота/внедрения:
  - заключить лицензионное соглашение
  - ограничить доступ по ролям (admin/employee)
  - включить аудит админ‑действий
  - запретить публичный доступ к контенту (только через API/presign)

### Production checklist

- Secrets:
  - `JWT_SECRET_KEY` задан и не дефолтный
  - `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` не дефолтные
- Network:
  - `CORS_ALLOW_ORIGINS` ограничен доменом(ами) фронта
- Storage:
  - включён TTL cleanup для `uploads/admin/*` (`UPLOADS_ADMIN_TTL_HOURS`)
  - настроены таймауты/ретраи S3 клиента (см. `backend/.env.example`)
- Backups:
  - ежедневный backup Postgres (вне сервера)
  - backup/replication объектного хранилища
- Observability:
  - логи собираются централизованно
  - healthchecks мониторятся

## Эксплуатация: Backup/Restore Postgres (Docker)

### Backup

```bash
docker compose exec -T postgres pg_dump -U sdlp -d sdlp > backup.sql
```

Рекомендовано для production (более надёжно и быстрее на больших БД):

```bash
docker compose exec -T postgres pg_dump -U sdlp -d sdlp -Fc > backup.dump
```

### Restore

```bash
docker compose exec -T postgres psql -U sdlp -d sdlp -f - < backup.sql
```

Restore из `backup.dump` (custom format):

```bash
docker compose exec -T postgres pg_restore -U sdlp -d sdlp --clean --if-exists < backup.dump
```

Рекомендация для production: хранить бэкапы вне сервера (S3/облако) и делать ежедневный бэкап по расписанию.

## Эксплуатация: Backup MinIO (файлы/контент)

Контент в MinIO хранится во volume `minio_data`. Для Docker-окружения самый простой вариант — бэкапить сам volume на уровне хоста.

Примечание: для production обычно удобнее настроить регулярное зеркало/экспорт в внешний S3 (или объектное хранилище) с помощью MinIO Client (`mc mirror`).

## Seed / миграции

- Миграции применяются автоматически при старте `backend` контейнера.
- Seed выполняется один раз и помечается файлом `/data/.seeded` во volume `backend_data`.

Чтобы пересоздать seed (только для dev/test):

```bash
docker compose down
docker volume rm "$(basename "$PWD")_backend_data"
docker compose up --build
```

## Smoke-check сценарии

- Войти пользователем
- Если выдан временный пароль и `must_change_password=true`:
  - система принуждает перейти на `/force-password-change`
  - после смены пароля доступ открывается
- Стартовать квиз и отправить ответы
- В админке:
  - создать пользователя
  - сбросить пароль пользователю
- Проверить `/health/ready`

## Dev hygiene (cleanup)

Локальная уборка мусора (освобождение места: `node_modules`, `.next`, `__pycache__`, caches):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\cleanup.ps1
```
