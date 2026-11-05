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
| `CORS_ALLOW_ORIGINS`                | домен сайта: кириллицей или в punycode — backend сравнивает ASCII-формы |
| `COOKIE_SECURE`                     | пусто (авто: Secure только на HTTPS) или `true` (сайт по https)    |
| `COOKIE_DOMAIN`                     | пусто (рекомендуется) либо домен в любой форме записи              |
| `AUTO_MIGRATE_ON_START`             | `false` (миграции применяются отдельной командой, см. п. 4)        |
| `curl -I https://…/health/ready`    | `HTTP/2 200`                                                      |
| `curl -I http://…/health/ready`     | `308` на https (если работает Caddy) или `200` (если сайт на nginx)|

Домены можно писать кириллицей: браузер всегда отправляет `Origin` и `Host` в
ASCII-форме (`https://edu.xn--80aaamzedb7cml.xn--p1ai`), поэтому backend и
frontend приводят значения из `.env` к ASCII перед сравнением. Раньше сравнение
шло «как есть»: CORS отвечал `403 invalid_origin` на каждый POST/PUT/PATCH/DELETE
(в том числе на вход), настройки показывали ложную ошибку домена, а `update.sh`
падал на самопроверке.

`COOKIE_DOMAIN` нужен только для общего входа на поддоменах. Если адрес сайта не
совпадает с этим доменом (вход по IP, временный адрес), фронтенд ставит куку
только для текущего хоста — вход работает, а не «теряется» молча.

## 3. Почему `docker compose logs backend` бывает пустым

`AUTO_MIGRATE_ON_START=true` запускает alembic в том же процессе, а
`alembic/env.py` вызывает `fileConfig`, который ставит корневому логгеру
уровень `WARN`. После этого `logging.basicConfig(level=INFO)` в приложении
бесполезен, и строки о каждом запросе молча пропадают — искать причину 500
по логу невозможно.

Исправлено: `create_app()` чинит конфигурацию (поднимает уровень и включает
логгер `corelms`), а `scripts/selfcheck.py` печатает строку «Уровень журнала»
и предупреждает, если журнал выключен. Проверить, что журнал живой:

```bash
docker compose exec -T backend python -c "import logging; print(logging.getLogger('corelms').getEffectiveLevel())"
docker compose logs backend --tail 5
```

Первая команда должна ответить `20` (INFO) — тогда `logs backend` показывает
строку на каждый запрос с полем `"status"`.

## 4. Где искать источник «Ошибка сервера. Повторите попытку позже.»

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

## 5. Проверка развёртывания и схемы

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

## 6. Полная самопроверка приложения изнутри контейнера

Скрипт `backend/scripts/selfcheck.py` (попадает в образ через `COPY . .`):

```bash
docker compose exec -T backend python scripts/selfcheck.py
```

Что печатает: окружение (секреты замаскированы), согласованность домена/CORS/кук,
диск и память, версию схемы против head, счётчики данных, Redis/очереди/воркеры,
доступность S3, последние серверные ошибки из журнала и каждый GET-эндпоинт под
временным администратором — статус, время, текст ошибки и traceback. Временная сессия удаляется в конце. POST/PUT/DELETE не вызываются.

Код возврата: `0` — чисто, `1` — есть 5xx/исключения/таймауты, `2` — только замечания по настройке.

## 7. Журнал ошибок в интерфейсе (без SSH)

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

## 8. Сборка, когда Docker Hub недоступен

Типичная картина в России: `git pull` проходит, а `docker compose build` падает на

```
failed to fetch anonymous token ... TLS handshake timeout
ERROR [backend internal] load metadata for docker.io/library/python:3.11-slim-bookworm
```

Важно: если после этого выполнить `docker compose up -d --no-deps backend frontend`,
контейнеры перезапустятся **на старых образах** — новый код не применится, и выглядит
это как «исправления не работают». Сначала убедись, что образ собрался:

```bash
docker images | grep -E 'corelms-(backend|frontend)'
```

`docker compose build --pull never …` **не работает**: в compose v2 `--pull` принимает
только `always|missing|never`, но флаг разбирается как имена сервисов, и получается
`no such service: never`.

Правильный путь без сети — собрать новый слой поверх уже существующего образа
(скрипт лежит в репозитории):

```bash
cd /opt/corelms
bash deploy/rebuild-offline.sh
```

Что делает скрипт:

* backend — `FROM corelms-backend:latest` + `COPY` исходников (`backend/`) в `/app`;
  зависимости не переустанавливаются, поэтому PyPI тоже не нужен;
* frontend — `yarn build` выполняется внутри старого образа `corelms-frontend:latest`
  (в нём уже есть `node_modules`), исходники монтируются только на чтение,
  публичный адрес API и переменные `NEXT_PUBLIC_*` берутся из `.env`;
* перед сборкой образы помечаются `corelms-backend:rollback-<дата>` /
  `corelms-frontend:rollback-<дата>` — откат одним `docker tag`.

Грабли этого способа: `COPY` приносит файлы с правами из репозитория, а
`backend/scripts/entrypoint.sh` лежит в git как `100644` (старый Dockerfile делал
`chmod +x` сам). Без этого бита контейнер падает на старте:

```
exec: "/app/scripts/entrypoint.sh": permission denied
```

Скрипт делает `chmod +x /app/scripts/*.sh` в новом слое, собирает образ в тег
`corelms-backend:next`, проверяет внутри `test -x /app/scripts/entrypoint.sh`
и только потом подменяет `:latest` — неудачная сборка больше не может оставить
нерабочий `latest`.

Перед подменой `:latest` скрипт делает дымовой тест: поднимает собранный
frontend-контейнер и ждёт, пока он ответит на `:3000`. Если контейнер падает,
печатаются его последние строки лога, а `:latest` остаётся прежним. `.next`
копируется в чистый каталог (`rm -rf /app/.next`), иначе `COPY` поверх старой
сборки оставляет куски прошлых чанков.

Проверка, что новый код действительно в образе:

```bash
docker compose exec -T backend python -c "from app.models.user import UserRole; print(sorted(r.value for r in UserRole))"
```

(Должно быть `['admin', 'employee', 'partner', 'superadmin']`.)

`docker compose run --rm --no-deps backend python -c "…"` для таких проверок **не
подходит**: контейнер стартует со своим entrypoint (alembic + uvicorn) и висит.
Либо `docker compose exec -T` в уже работающем контейнере, либо
`docker run --rm --entrypoint python corelms-backend:latest -c "…"`.

## 9. Обновление без потери данных

```bash
cd /opt/corelms
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > /srv/backups/pre-deploy-$(date +%F_%H-%M).dump
git pull --ff-only
bash deploy/rebuild-offline.sh
docker compose up -d --no-deps backend worker worker_media frontend
docker compose ps
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend python scripts/selfcheck.py
curl -sS https://<домен>/health/ready ; echo
```

Порядок важен: миграции запускаются уже на новом образе, поэтому `alembic upgrade head`
идёт **после** `up -d`. Воркеры перезапускаются вместе с backend — они работают на том же
образе, иначе импорт продолжит работать на старом коде. Перезапуск воркеров прерывает
текущие задачи, поэтому обновляйся, когда импортов в работе нет.

Никогда не использовать `docker compose down -v`, `docker volume rm pg_data`, `--renew-anon-volumes`:
Postgres живёт в томе `pg_data`, файлы — в S3, загрузки — в томе `backend_data`.

**Не переименовывайте каталог с `docker-compose.yml`.** Docker Compose образует имя тома
из имени проекта, а имя проекта по умолчанию — это имя каталога: в `/opt/corelms` том
называется `corelms_pg_data`, в `/opt/lms` — уже `lms_pg_data`. После переименования
compose создаст новый пустой том, и платформа запустится с пустой базой (старые данные
останутся в прежнем томе и найдутся через `docker volume ls`). Если каталог всё же нужно
перенести, задайте имя проекта заранее в `.env` (`COMPOSE_PROJECT_NAME=<прежнее имя>`) и
проверьте, что `docker volume ls` показывает тот же том. Переименование каталога на
работающей установке — только после `deploy/backup.sh`.
Redis хранит сессии и очереди — при пересоздании контейнера сессии пропадут (пользователи
просто войдут заново), но задачи в очередях лучше дождаться.

## 10. «С телефона не входит»: как найти причину за минуту

Версия кода, которая реально работает, теперь видна снаружи:

```bash
curl -sS https://edu.каркастайги.рф/health/version
```

Если ответа нет или в нём `"version": "dev"` — деплой не применён (на сервере
старый код либо `deploy/update.sh` не запускался): `APP_VERSION` проставляет
именно `update.sh`, поэтому `"dev"` означает «собрано не этим скриптом».

Дальше — диагностика прямо на форме входа. Она показывает с точки зрения сервера
схему запроса, домен куки, доступность API и то, какие куки реально пришли:

```bash
curl -sS https://edu.каркастайги.рф/api/diagnostics/client | python3 -m json.tool
```

На телефоне: откройте форму входа → «Не получается войти? Проверить подключение»
(панель раскрывается сама после любой ошибки входа) → пришлите этот блок.

Что означают проверки:

| Проверка | Плохо, если | Что делать |
| --- | --- | --- |
| Соединение по HTTPS | `https: false` | открывать `https://…`, проверить Caddy/сертификат |
| Домен куки | текст «не совпадает с адресом» | `COOKIE_DOMAIN` не соответствует домену сайта; вход при этом работает (кука станет host-only) |
| Флаг Secure | «без Secure» при `https: true` | прокси не передаёт `X-Forwarded-Proto: https` (см. `map $http_x_forwarded_proto` в `nginx/default.conf`) |
| Сервис API | «не ответил» | backend лежит/перезапускается: `docker compose ps`, `docker compose logs --tail=100 backend` |
| Куки сессии в запросе | пусто после успешного входа | браузер выбросил куку: приватный режим, встроенный браузер мессенджера, «экономия трафика» |

Если в логах фронтенда появилось `[corelms] login rejected by origin check`, там
же напечатаны пришедший `Origin`, `Host`, `PUBLIC_APP_URL` и `CORS_ALLOW_ORIGINS`:

```bash
docker compose logs --tail=200 frontend | grep "login rejected"
```

Причина в этом случае одна: адрес, по которому открыт сайт, не совпадает с
`PUBLIC_APP_URL`/`CORS_ALLOW_ORIGINS`. Кириллица и punycode (`edu.каркастайги.рф`
и `edu.xn--80aaamzedb7cml.xn--p1ai`), а также «сырой» UTF-8 в заголовке `Origin`
теперь считаются одним и тем же адресом.

Старые куки от прежнего адреса сайта мешают входу (браузер присылает две копии
`core_token`): в кабинете нажмите «Выйти» (выход гасит обе копии) либо очистите
данные сайта в браузере телефона.

## 11. Проверка docker-compose.yml до деплоя

Docker Compose падает на дубликате ключа в службе, а PyYAML такое молча
проглатывает:

```
failed to parse /opt/corelms/docker-compose.yml: yaml: construct errors:
  line 1: line 220: mapping key "environment" already defined at line 208
```

Ошибка вылезала **после** сборки образов, когда `compose up` уже ничего не мог
сделать. Теперь структура файла проверяется до сборки:

```bash
cd /opt/corelms
python3 deploy/check-compose.py docker-compose.yml
```

Скрипт находит дубликаты ключей, повторяющиеся переменные в одном списке
`environment`, `depends_on` на несуществующую службу и, если в системе есть
Docker, дополнительно запускает `docker compose config -q`. Тот же скрипт
запускают `deploy/update.sh` и `deploy/rebuild-offline.sh` в самом начале, а
`pytest` (`backend/tests/test_compose_file.py`) и CI — на каждый коммит.

## 12. «Захожу и сразу вылетает»: дубли кук и кэш персональных данных

### Причина

Диагностика на форме входа показывала в запросе **только `core_refresh`** —
куки доступа не было. Отсюда две проблемы, которые складывались в «вхожу и
сразу вылетаю».

1. **Дубли кук.** `COOKIE_DOMAIN` включили позже, чем начали работать: у части
   пользователей в браузере остались host-only `core_token`/`core_refresh` с
   прежнего адреса. Браузер присылает обе копии, а `request.cookies.get()` и
   `next/headers` возвращают первую — самую старую. Дальше: сервер получает
   просроченный токен, отвечает 401, страница уводит на главную.
   Дополнительно `NextResponse.cookies.set()` хранит куки в Map по имени, и
   удаление старой копии (`Max-Age=0` без Domain) молча пропадало — поэтому
   дубли не исчезали никогда.

2. **Ответ 401 на `/api/backend/*` приводил к жёсткому переходу на `/`** —
   промо-страница выглядит как «меня выкинуло» без всякого объяснения.

### Что сделано

- `frontend/src/app/api/auth/_jar.ts`: читаются **все** копии куки; токен
  доступа выбирается по `exp` (свежий первым), refresh — с конца заголовка,
  и если сервер отверг один, пробуется следующий.
- куки пишутся через `headers.append("set-cookie", …)` — удаление host-only
  копии и установка доменной уходят **двумя** заголовками.
- `/api/backend/*` при 401 обновляет сессию на сервере и повторяет запрос
  (для GET/HEAD — с повтором; для методов с телом — до отправки), поэтому
  отсутствие куки доступа больше не выкидывает из кабинета.
- выход отзывает все копии refresh-токена и гасит обе куки.
- 401 уводит на `/login?redirect=…&reason=session` с пояснением, а не на `/`.
- диагностика показывает число копий кук — причину видно сразу.

### Кэш персональных данных

Ответы `/api/backend/*` с авторизацией теперь помечаются
`Cache-Control: private, no-store` (+ `Vary: Cookie, Authorization`); потоки
видео/PDF — `private, max-age=0`. Сессионные куки больше не передаются в
backend (API авторизуется заголовком). Uvicorn не отдаёт заголовок
`Server: uvicorn` (`server_header=False`).

### Проверка

```bash
# в браузере: форма входа → «Проверить подключение» → «копий core_token»
curl -sS https://<домен>/api/diagnostics/client | python3 -m json.tool
```

## 13. Мобильная и десктопная вёрстка: навигация, отступы, таблицы

### Что было не так с меню «Админ‑центр»

Шапка показывала на телефоне ту же ленту пунктов, что и на десктопе
(`Дашборд · Обучение · Продажи · Кабинет · Админ‑центр`). Замер подписей
(10 px, bold, uppercase, tracking 0.05em) даёт:

| Пункт | ширина пункта |
| --- | --- |
| Дашборд | 75 px |
| Обучение | 76 px |
| Продажи | 74 px |
| Кабинет | 68 px |
| Админ‑центр | 97 px |
| **итого с отступами, gap и padding** | **≈ 420 px** |

Доступно на iPhone: 390 px минус поля 32 px = **358 px**. Лента имела
`overflow-x-auto`, поэтому не ломала страницу, но пятый пункт просто уезжал
за правый край — без подсказки, что её можно прокрутить. Отсюда жалоба
«меню админ центр уходит за экран».

### Что сделано

Пункты меню вынесены в один модуль `src/lib/navigation.ts` (подпись для
десктопа + короткая подпись для телефона) и используются двумя компонентами:

| Ширина экрана | Где навигация |
| --- | --- |
| < 768 px (телефон) | нижняя панель вкладок: иконка + подпись, ничего не уезжает |
| 768–1279 px (планшет, небольшой ноутбук) | лента под логотипом (влезает: 720 px против 420 px) |
| ≥ 1280 px (десктоп) | как раньше — по центру шапки |

Нижняя панель учитывает «челку» (`env(safe-area-inset-bottom)`), контент
получает отступ снизу, уведомления и «закреплённые» панели действий подняты
над ней, модальные окна (z-100) её перекрывают.

### Попутно исправлено в этом же проходе

- `min-h-screen` → `min-h-dvh`: на iPhone `100vh` выше видимой области, из-за
  чего низ страницы уходил под панель браузера.
- Поля страниц на телефоне: `px-6` → `px-4 sm:px-6` (dashboard, обучение,
  кабинет, модули, лендинг); карточки `p-8/p-10` → `p-5 sm:p-8`. На 360 px
  это возвращает ~40 px полезной ширины.
- Ленты разделов (редактор модуля, продажи, вкладки урока) на телефоне
  переносятся на вторую строку вместо горизонтальной прокрутки.
- В обучении свёрнутый блок «Содержание» показывает текущий урок: раньше
  на телефоне было видно только «Содержание · N · Открыть».
- Таблицы админки (пользователи, результаты) остаются прокручиваемыми, но на
  телефоне над ними появилась подсказка о прокрутке.

### Права и публичные эндпоинты — проверено на собранном приложении

```
=== ПУБЛИЧНЫЕ ЭНДПОИНТЫ (без токена) ===
GET    /health        GET /health/live    GET /health/ready   GET /health/version
POST   /auth/token    POST /auth/refresh  POST /auth/logout
POST   /auth/register                    POST /auth/reset-password/confirm
POST   /health/cron/admin-uploads-cleanup  POST /health/cron/run-all
```
`/auth/register` закрыт настройкой (`ALLOW_PUBLIC_REGISTER`), cron-эндпоинты
требуют `x-cron-secret` и при незаданном секрете отвечают 404.

```
=== ДОСТУП ПО РОЛЯМ ===
админ       /auth/me 200  /modules 200  /admin/users 200  /admin/diagnostics/errors 200
партнёр     /auth/me 200  /modules 200  /admin/users 403  /admin/diagnostics/errors 403
без токена  /auth/me 401  /modules 401  /admin/users 401  /admin/diagnostics/errors 401
```

Дополнительно в этом проходе прокси `/api/backend/*` больше не пропускает
заголовок `Authorization` от клиента: единственный источник авторизации —
httpOnly-кука.

### Пустой экран на слабой сети

`/login` и `/` до загрузки JS отдавали пустой белый документ (форма входа
использует `useSearchParams`, поэтому сервер отдаёт заготовку). Теперь в HTML
сразу приходит фирменная заставка «Открываем форму входа…» / «Загружаем
платформу…» — проверено ответом сервера:

```
$ curl -s http://127.0.0.1:3200/login | grep -o "Открываем форму входа"
Открываем форму входа        # длина HTML 8908 байт против 7369 до правки
$ curl -s http://127.0.0.1:3200/ | grep -o "Загружаем платформу"
Загружаем платформу
```

### Найдено при чтении кода в этом проходе

- **Нечитаемые ошибки на обязательных экранах.** На «Смене пароля» и
  «Восстановлении пароля» текст ошибки был `text-red-200` на светлом фоне
  `bg-red-500/10` — практически не виден. Стало `text-red-800` на `bg-red-50`
  + `role="alert"`.
- **Утечка внутреннего адреса API.** `/api/diagnostics/client` доступен без
  входа и возвращал `detail` ошибки `fetch` — там бывает
  `connect ECONNREFUSED 10.0.0.5:8000`. Теперь наружу уходит только
  «backend не ответил», а причина пишется в серверный лог.
- **Перенос папок в «Продажах» только мышью.** На телефоне drag&drop
  не работает, поэтому в меню файла/папки появились кнопки
  «Переместить в: …» (на уровень выше и любая папка текущего каталога).

## 14. Сквозной проход: права, архив пользователей, отсутствие «мёртвых» вызовов

Проверка «каждой функции», а не выборочная: сценарии прогоняются по всему
списку маршрутов FastAPI, а не по тем, что пришли в голову.

### Гость не получает ни одного закрытого ответа

Скрипт перебирает **все** маршруты приложения (206 штук, включая
`APIRouter(dependencies=[...])`, которые не видны при статическом разборе
`route.dependant`) и шлёт запрос без токена. 200 допустим только для публичных.

```
всего маршрутов: 206
утечек без токена: 0
```

Публичных ровно 11: `/health`, `/health/live`, `/health/ready`,
`/health/version`, `POST /auth/token`, `POST /auth/refresh`,
`POST /auth/logout`, `POST /auth/register`, `POST /auth/reset-password/confirm`
и два cron-эндпоинта `/health/cron/*` (без `x-cron-secret` — 404).

Партнёр с настоящим токеном: `/auth/me`, `/modules` — 200; `/admin/users`,
`/admin/diagnostics/errors` — 403; без токена — 401. Проверено и раньше,
повторено после правок этого прохода.

### Удаление пользователя падало и стирало историю

`DELETE /admin/users/{id}` на человеке, которому выдали тег, возвращал 500:
строка `user_tag_map` оставалась, и Postgres отказывал по внешнему ключу.
Воспроизведено пробником на SQLite с `PRAGMA foreign_keys=ON`:
`IntegrityError: FOREIGN KEY constraint failed`. Плюс само удаление уносило
попытки тестов и прогресс — это противоречит правилу «история ученика не
удаляется».

Теперь так же, как с модулями и уроками:

```
DELETE /admin/users/{id}              → архив: вход закрыт, из списков скрыт,
                                        история и теги сохранены
POST   /admin/users/{id}/restore      → вернуть, доступ снова работает
DELETE /admin/users/{id}?permanent=true
                                      → только если истории нет совсем;
                                        иначе 409 с объяснением
```

Архивная запись не пускается ни по паролю (403 `account_archived`), ни по
ранее выданному токену (401 — проверка `is_archived` в `get_current_user`),
ни по refresh; активные сессии отзываются сразу. Архивные не попадают в
список пользователей, в счётчики и в аналитику; назначить им задание нельзя
(409). Проверено тестами `backend/tests/test_user_archive.py` (4 сценария).

### Одна роль — одно имя

`/auth/me` отдавал обучающемуся `"user"`, а тип `User.role` на фронте и
фильтры админки ожидали `"employee"`, при этом `partner` проходил как есть.
Теперь наружу всегда `employee` (backend и прокси `/api/auth/me`), сравнения
ролей на фронте по-прежнему только `admin`/`superadmin`.

### Причина отказа входа доходит до человека

Прокси `/api/auth/login` подменял любой 403 на «Проверьте CORS_ALLOW_ORIGINS».
После появления архива это показывало неверную причину: человек с архивной
записью шёл искать настройки сервера. Теперь сообщение сервера
(`error_message`) показывается как есть, а подсказка про CORS осталась только
для `invalid_origin`.

### Нет вызовов «в никуда»

Все адреса, которые фронт запрашивает через `apiFetch` (36 статических и 37
шаблонных), сверены со списком маршрутов бэкенда: совпадений нет — нет ни
одного запроса к несуществующему эндпоинту.

```
уникальных статических вызовов: 36, не найдено: 0
шаблонных вызовов: 37, не найдено: 0
```

### Живой прогон (не только тесты)

Поднят реальный стек: backend `uvicorn` + Next (`next start`) + Redis по
протоколу (fakeredis TCP), вход через `/api/auth/login`, все запросы — через
прокси `/api/backend/*`, то есть тем же путём, что и браузер.

```
DELETE /admin/users/{id}                  → {"ok":true,"archived":true,...} 200
вход архивного                            → 403 account_archived
список /admin/users                       → только действующие
список ?include_archived=true             → человек с пометкой is_archived и тегом
POST /admin/users/{id}/restore            → 200, вход снова работает
DELETE /admin/users/{id}?permanent=true   → 200, users=0 и user_tag_map=0 в базе
партнёр → /admin/users, /admin/settings/* → 403
партнёр → /me/profile, /me/history        → 200 после смены временного пароля
старый токен после смены пароля           → backend 401, /api/auth/me {authenticated:false}
/admin/users без сессии                   → 307 на /login?redirect=%2Fadmin%2Fusers
```

Последний пункт важен для «никаких утечек»: прокси чтения сессии отвечает 200
и телом `{"authenticated":false}` — это не выдача данных, а признак «сессии
нет» (заголовок `Cache-Control: private, no-store`).
