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
#   bash deploy/rebuild-offline.sh            # backend и frontend
#   bash deploy/rebuild-offline.sh backend    # только backend
#   bash deploy/rebuild-offline.sh frontend   # только frontend
#
# Данные не затрагиваются: меняются только образы. Теги для отката — *:rollback-<дата>.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
STAMP="$(date +%F_%H-%M)"
WHAT="${1:-all}"

say() { printf '\n== %s\n' "$1"; }

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

build_backend() {
  say "Backend: новый слой поверх текущего образа"
  docker image inspect corelms-backend:latest >/dev/null 2>&1 || {
    echo "нет образа corelms-backend:latest — сначала нужен хотя бы один собранный образ"; exit 1; }
  tag_rollback "corelms-backend:latest"
  cat > backend/Dockerfile.offline <<'DOCKER'
FROM corelms-backend:latest
USER root
COPY --chown=app:app . /app
USER app
DOCKER
  docker build -f backend/Dockerfile.offline -t corelms-backend:latest backend
  rm -f backend/Dockerfile.offline
  echo "backend готов"
}

build_frontend() {
  say "Frontend: пересборка Next.js внутри текущего образа"
  docker image inspect corelms-frontend:latest >/dev/null 2>&1 || {
    echo "нет образа corelms-frontend:latest — сначала нужен хотя бы один собранный образ"; exit 1; }
  tag_rollback "corelms-frontend:latest"

  # Публичный адрес API зашивается в браузерный бандл на этапе сборки.
  local public_base
  public_base="$(env_get NEXT_PUBLIC_API_BASE_URL)"
  [ -n "$public_base" ] || public_base="https://$(env_get CADDY_DOMAIN)"
  [ "$public_base" != "https://" ] || public_base="http://127.0.0.1:8888"

  local out=/tmp/corelms-frontend-layer
  rm -rf "$out"; mkdir -p "$out"

  # node_modules уже есть в образе — берём их оттуда, исходники монтируем только на чтение.
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
  docker build -t corelms-frontend:latest "$out"
  rm -rf "$out"
  echo "frontend готов (NEXT_PUBLIC_API_BASE_URL=$public_base)"
}

case "$WHAT" in
  backend) build_backend ;;
  frontend) build_frontend ;;
  all) build_backend; build_frontend ;;
  *) echo "Неизвестный аргумент: $WHAT (backend | frontend | all)"; exit 1 ;;
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
