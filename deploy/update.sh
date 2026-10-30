#!/usr/bin/env bash
# Обновление CoreLMS без Docker Hub.
#
# Зачем: на сервере бывает закрыт доступ к registry-1.docker.io, и
#   docker compose up -d --build
# падает с «failed to fetch anonymous token ... TLS handshake timeout».
# При этом базовые образы для сборки не нужны: новые образы собираются
# поверх уже работающих (corelms-backend:latest и т.д.), исходники копируются
# внутрь. Данные (pg_data, S3, backend_data, redis_data) не затрагиваются.
#
# Использование:
#   bash deploy/update.sh            # backend, воркеры, frontend — без сети
#   bash deploy/update.sh backend    # только backend
#   bash deploy/update.sh frontend   # только frontend
#   bash deploy/update.sh workers    # только воркеры очередей
#   bash deploy/update.sh --build    # сначала попробовать обычную сборку с Docker Hub
#
# Что делает по шагам:
#   1) собирает образы (офлайн, с тегами отката);
#   2) поднимает контейнеры приложений без --build (сеть не нужна);
#   3) применяет миграции базы и проверяет, что API отвечает;
#   4) печатает команды откатa, если что-то не так.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
STAMP="$(date +%F_%H-%M)"
WHAT="all"
TRY_BUILD=0

for arg in "$@"; do
  case "$arg" in
    --build) TRY_BUILD=1 ;;
    backend|frontend|workers|all) WHAT="$arg" ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "Неизвестный аргумент: $arg (backend | frontend | workers | all | --build)"; exit 2 ;;
  esac
done

say() { printf '\n== %s\n' "$1"; }
die() { printf '\n!! %s\n' "$1"; exit 1; }

command -v docker >/dev/null 2>&1 || die "Docker не найден"
docker compose version >/dev/null 2>&1 || die "Нужен Docker Compose v2 (команда 'docker compose')"

# Тома с данными не трогаем никогда: они перечислены только для проверки.
DATA_VOLUMES="pg_data redis_data backend_data s3_data caddy_data caddy_config"
say "Проверка томов с данными"
docker volume ls --format '{{.Name}}' | grep -E "^(${DATA_VOLUMES// /|})\$|_(${DATA_VOLUMES// /|})\$" || true

if [ "$TRY_BUILD" -eq 1 ]; then
  say "Пробуем обычную сборку (нужен доступ к Docker Hub)"
  attempt=1
  until docker compose build; do
    if [ "$attempt" -ge 3 ]; then
      echo "Сеть до Docker Hub недоступна — переходим на офлайн-сборку из текущих образов."
      break
    fi
    attempt=$((attempt + 1))
    echo "Повтор сборки через $((attempt * 10)) с…"
    sleep $((attempt * 10))
  done
fi

# Образы приложения обязаны существовать: иначе офлайн-сборке не от чего отталкиваться.
for image in corelms-backend:latest corelms-frontend:latest; do
  docker image inspect "$image" >/dev/null 2>&1 || die "Нет образа $image. Первая установка требует доступа к Docker Hub: см. deploy/pull-base-images.sh"
done

say "Сборка образов из исходников (без Docker Hub)"
bash deploy/rebuild-offline.sh "$WHAT"

# Раньше воркеров было четыре (worker_import / worker_regen / worker_default).
# После объединения их в один сервис `worker` старые контейнеры остались бы
# работать со старым кодом и разбирать очередь: убираем их при обновлении.
say "Убираем контейнеры воркеров старой схемы"
for legacy in worker_import worker_regen worker_default; do
  for name in $(docker ps -a --filter "name=${legacy}" --format '{{.Names}}'); do
    case "$name" in
      *"${legacy}"*) docker rm -f "$name" >/dev/null 2>&1 && echo "  удалён $name" ;;
    esac
  done
done

say "Поднимаем контейнеры приложений"
# --no-build: compose не пытается собрать заново и не обращается к registry.
docker compose up -d --no-build --no-deps backend worker worker_media
if [ "$WHAT" = "all" ] || [ "$WHAT" = "frontend" ]; then
  docker compose up -d --no-build --no-deps frontend
fi

say "Ждём готовности API"
ready=0
for _ in $(seq 1 60); do
  if docker compose exec -T backend python - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=3)
PY
  then ready=1; break; fi
  sleep 2
done
[ "$ready" -eq 1 ] || die "API не ответил за 2 минуты. Логи: docker compose logs --tail=80 backend"

say "Миграции базы"
docker compose exec -T backend alembic upgrade head

say "Самопроверка"
# selfcheck: 0 — всё хорошо, 2 — предупреждения настройки, 1 — ошибки эндпоинтов.
# Раньше любое предупреждение (например, кириллический COOKIE_DOMAIN) роняло
# обновление уже после того, как контейнеры поднялись. Теперь обновление
# завершается, а предупреждения просто печатаются.
check_code=0
docker compose exec -T backend python scripts/selfcheck.py || check_code=$?
if [ "$check_code" -eq 1 ]; then
  die "Самопроверка нашла ошибки эндпоинтов (или не смогла их проверить). Смотрите вывод выше и логи: docker compose logs --tail=80 backend"
fi
if [ "$check_code" -ne 0 ] && [ "$check_code" -ne 2 ]; then
  echo "!! Самопроверка завершилась с кодом $check_code — контейнеры уже подняты, проверьте сайт вручную."
fi
if [ "$check_code" -eq 2 ]; then
  echo "Предупреждения настройки выше. Они не отменяют обновление — исправьте .env и выполните bash deploy/update.sh ещё раз."
fi

say "Готово"
cat <<NEXT
Изменения действуют. Проверка из браузера: откройте сайт и раздел «Админ-центр → Настройки».

Откат образов (если что-то не так):
  docker tag corelms-backend:rollback-${STAMP} corelms-backend:latest
  docker tag corelms-frontend:rollback-${STAMP} corelms-frontend:latest
  docker compose up -d --no-build --no-deps backend worker worker_media frontend

Данные при откате не меняются: база и файлы остаются на месте.
NEXT
