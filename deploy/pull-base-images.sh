#!/usr/bin/env bash
# Скачивание базовых образов с повторами — лечение ошибки
#   failed to fetch anonymous token ... net/http: TLS handshake timeout
#
# Docker Hub иногда отвечает медленно; одна неудачная попытка не означает,
# что registry недоступен. Скрипт повторяет загрузку с паузой и в конце
# честно говорит, чего не хватает.
#
# Использование:
#   bash deploy/pull-base-images.sh
#
# Если все попытки провалились, есть три рабочих варианта:
#   1) повторить позже — чаще всего это временная сеть провайдера;
#   2) указать зеркало в /etc/docker/daemon.json (см. README, раздел «Обновление»);
#   3) собирать без сети: bash deploy/update.sh (образы corelms-* уже локально).

set -uo pipefail

IMAGES=(
  "python:3.11-slim-bookworm"
  "node:20-slim"
  "postgres:16"
  "redis:7"
  "nginx:1.27-alpine"
  "caddy:2"
  "alpine:3.20"
)

command -v docker >/dev/null 2>&1 || { echo "Docker не найден"; exit 1; }

failed=()
for image in "${IMAGES[@]}"; do
  if docker image inspect "$image" >/dev/null 2>&1; then
    echo "уже локально: $image"
    continue
  fi
  ok=0
  for attempt in 1 2 3 4 5; do
    echo "скачиваем $image (попытка $attempt из 5)"
    if docker pull "$image"; then ok=1; break; fi
    sleep $((attempt * 8))
  done
  [ "$ok" -eq 1 ] || failed+=("$image")
done

if [ "${#failed[@]}" -eq 0 ]; then
  echo "Все базовые образы на месте — сборка пойдёт без обращений к registry."
  exit 0
fi

printf '\nНе удалось скачать: %s\n' "${failed[*]}"
cat <<'HELP'

Что делать:
  1) Повторите позже: TLS handshake timeout обычно временный.
  2) Зеркало registry — в /etc/docker/daemon.json:
       { "registry-mirrors": ["https://mirror.gcr.io"] }
     затем: systemctl restart docker
  3) Собрать без сети: bash deploy/update.sh
     (работает, если образы corelms-backend:latest и corelms-frontend:latest уже есть).
HELP
exit 1
