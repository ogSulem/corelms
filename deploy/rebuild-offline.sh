#!/usr/bin/env bash
# Сборка новых образов без обращения к Docker Hub.
#
# Нужно, когда `docker compose build` падает на
#   failed to fetch anonymous token ... TLS handshake timeout
# Базовые образы (python:3.11-slim-bookworm / node:20-slim) скачать нельзя,
# но они и не нужны: новый слой строится поверх уже собранного образа,
# внутрь копируются только исходники и свежая сборка Next.js.
#
# Использование:
#   bash deploy/rebuild-offline.sh            # backend, frontend и воркеры
#   bash deploy/rebuild-offline.sh backend    # только backend
#   bash deploy/rebuild-offline.sh frontend   # только frontend
#   bash deploy/rebuild-offline.sh workers    # только воркеры очередей
#
# Данные не затрагиваются: меняются только образы. Теги для отката — *:rollback-<дата>.
#
# Сборка идёт в тег `*:next`, проверяется и только потом подменяет `:latest`.
# Поэтому неудачная сборка никогда не оставляет рабочий тег нерабочим.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
STAMP="$(date +%F_%H-%M)"
WHAT="${1:-all}"

WORKER_IMAGES="corelms-worker_import corelms-worker_regen corelms-worker_media corelms-worker_default"

say() { printf '\n== %s\n' "$1"; }
die() { printf '\n!! %s\n' "$1"; exit 1; }

# Значение из .env (без кавычек), пусто — если ключа нет.
env_get() {
  local key="$1"
  [ -f "$ROOT/.env" ] || return 0
  sed -n "s/^[[:space:]]*${key}=//p" "$ROOT/.env" | tail -n 1 | tr -d "\"'" | tr -d '\r'
}

tag_rollback() {
  local image="$1"
  if docker image inspect "$image" >/dev/null 2>&1; then
    docker tag "$image" "${image%%:*}:rollback-${STAMP}"
    echo "откат: ${image%%:*}:rollback-${STAMP}"
  fi
}

# Общий слой для всех python-образов: исходники + бит исполнения у скриптов.
python_layer() {
  local base="$1"
  local target="$2"
  cat > backend/Dockerfile.offline <<DOCKER
FROM ${base}:latest
USER root
COPY --chown=app:app . /app
RUN chmod +x /app/scripts/*.sh
USER app
DOCKER
  docker build -f backend/Dockerfile.offline -t "${target}:next" backend
}

build_backend() {
  say "Backend: новый слой поверх текущего образа"
  docker image inspect corelms-backend:latest >/dev/null 2>&1 \
    || die "нет образа corelms-backend:latest — не от чего собирать"
  chmod +x backend/scripts/*.sh 2>/dev/null || true
  tag_rollback "corelms-backend:latest"
  python_layer corelms-backend corelms-backend
  rm -f backend/Dockerfile.offline

  docker run --rm --entrypoint sh corelms-backend:next \
    -c 'test -x /app/scripts/entrypoint.sh && test -f /app/app/main.py' \
    || die "в новом образе entrypoint.sh не исполняемый — latest не меняю, старый образ цел"

  docker tag corelms-backend:next corelms-backend:latest
  echo "backend готов"
}

build_workers() {
  local image
  for image in $WORKER_IMAGES; do
    if ! docker image inspect "${image}:latest" >/dev/null 2>&1; then
      echo "нет образа ${image}:latest — пропускаю"
      continue
    fi
    say "Воркер ${image}: новый слой поверх текущего образа"
    tag_rollback "${image}:latest"
    python_layer "$image" "$image"
    docker run --rm --entrypoint sh "${image}:next" -c 'test -f /app/app/main.py' \
      || die "в образе ${image}:next нет кода — latest не меняю"
    docker tag "${image}:next" "${image}:latest"
  done
  rm -f backend/Dockerfile.offline
  echo "воркеры готовы"
}

build_frontend() {
  say "Frontend: пересборка Next.js внутри текущего образа"
  docker image inspect corelms-frontend:latest >/dev/null 2>&1 \
    || die "нет образа corelms-frontend:latest — не от чего собирать"
  tag_rollback "corelms-frontend:latest"

  # Публичный адрес API зашивается в браузерный бандл на этапе сборки.
  local public_base
  public_base="$(env_get NEXT_PUBLIC_API_BASE_URL)"
  [ -n "$public_base" ] || public_base="https://$(env_get CADDY_DOMAIN)"
  [ "$public_base" != "https://" ] || public_base="http://127.0.0.1:8888"

  local out=/tmp/corelms-frontend-layer
  rm -rf "$out"; mkdir -p "$out"

  # node_modules уже есть в образе — исходники монтируем только на чтение.
  docker run --rm -u root \
    -v "$ROOT/frontend:/src:ro" \
    -v "$out:/out" \
    -e NEXT_TELEMETRY_DISABLED=1 \
    -e NODE_ENV=production \
    -e NEXT_PUBLIC_API_BASE_URL="$public_base" \
    -e NEXT_PUBLIC_QUICKSTART_ASSET_ID="$(env_get NEXT_PUBLIC_QUICKSTART_ASSET_ID)" \
    -e NEXT_PUBLIC_QUICKSTART_VIDEO_URL="$(env_get NEXT_PUBLIC_QUICKSTART_VIDEO_URL)" \
    -e NEXT_PUBLIC_TELEGRAM_SUPPLIERS_BASE_URL="$(env_get NEXT_PUBLIC_TELEGRAM_SUPPLIERS_BASE_URL)" \
    -w /tmp corelms-frontend:latest \
    sh -c 'set -e; rm -rf /tmp/build; cp -a /src /tmp/build; rm -rf /tmp/build/node_modules /tmp/build/.next /tmp/build/tests; ln -s /app/node_modules /tmp/build/node_modules; cd /tmp/build; yarn build; rm -rf /out/.next; cp -a .next /out/.next'

  cat > "$out/Dockerfile" <<'DOCKER'
FROM corelms-frontend:latest
COPY --chown=node:node .next /app/.next
DOCKER
  docker build -t corelms-frontend:next "$out"
  docker run --rm --entrypoint sh corelms-frontend:next -c 'test -f /app/.next/BUILD_ID' \
    || die "новый .next не попал в образ — latest не меняю"
  docker tag corelms-frontend:next corelms-frontend:latest
  rm -rf "$out"
  echo "frontend готов (NEXT_PUBLIC_API_BASE_URL=$public_base)"
}

case "$WHAT" in
  backend) build_backend ;;
  frontend) build_frontend ;;
  workers) build_workers ;;
  all) build_backend; build_workers; build_frontend ;;
  *) die "Неизвестный аргумент: $WHAT (backend | frontend | workers | all)" ;;
esac

say "Готово. Дальше по порядку:"
cat <<NEXT
  cd $ROOT
  docker compose up -d --no-deps backend worker_import worker_regen worker_media worker_default frontend
  docker compose ps
  docker compose exec -T backend alembic upgrade head
  docker compose exec -T backend python scripts/selfcheck.py
  curl -sS https://<домен>/health/ready ; echo

Откат образов:
  docker tag corelms-backend:rollback-${STAMP} corelms-backend:latest
  docker tag corelms-frontend:rollback-${STAMP} corelms-frontend:latest
  docker compose up -d --no-deps backend worker_import worker_regen worker_media worker_default frontend
NEXT
