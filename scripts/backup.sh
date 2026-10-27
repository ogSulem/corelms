#!/usr/bin/env bash
# Согласованная резервная копия CoreLMS: PostgreSQL + файлы из локального тома.
#
# Запуск на сервере из каталога с docker-compose.yml:
#   ./scripts/backup.sh                 # ./backups, хранить 14 копий
#   ./scripts/backup.sh --keep 30       # хранить 30 копий
#   ./scripts/backup.sh --dir /srv/backups --redis
#
# Каждая копия — отдельный каталог backups/corelms-YYYY-mm-dd_HH-MM-SS:
#   db.dump        полный дамп PostgreSQL (pg_dump -Fc)
#   files.tar.gz   том backend_data (/data), если он используется
#   dump.rdb       снимок Redis (только с --redis; не обязателен для восстановления)
#   env.backup     копия .env с правами 600 (в ней пароль БД и ключи)
#   MANIFEST.txt   версия схемы, размеры, контрольные суммы
#
# Скрипт ничего не удаляет в БД и не останавливает сервисы. Данные в томах
# pg_data / backend_data переживают обновления кода, но резервная копия нужна
# перед миграциями, переездом и на случай ошибки человека.
set -Eeuo pipefail

COMPOSE="${COMPOSE:-docker compose}"
DIR="./backups"
KEEP=14
WITH_REDIS=0
WITH_FILES=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) DIR="$2"; shift 2 ;;
    --keep) KEEP="$2"; shift 2 ;;
    --redis) WITH_REDIS=1; shift ;;
    --no-files) WITH_FILES=0; shift ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "Неизвестный параметр: $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."
[[ -f docker-compose.yml ]] || { echo "Нет docker-compose.yml рядом со скриптом" >&2; exit 1; }

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
PG_DB="${POSTGRES_DB:-sdlp}"
PG_USER="${POSTGRES_USER:-sdlp}"

STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
TARGET="${DIR}/corelms-${STAMP}"
mkdir -p "$TARGET"
chmod 700 "$DIR" "$TARGET"
echo "→ Резервная копия: $TARGET"

# 1. База данных. -T обязателен: иначе дамп смешается с выводом TTY.
echo "→ PostgreSQL"
$COMPOSE exec -T postgres sh -c "pg_dump -U '$PG_USER' -d '$PG_DB' -Fc" > "$TARGET/db.dump"
if [[ ! -s "$TARGET/db.dump" ]]; then
  echo "Дамп пустой — копия не создана" >&2
  rm -rf "$TARGET"
  exit 1
fi
# Сразу проверяем, что дамп читается: битая копия хуже отсутствующей.
$COMPOSE exec -T postgres pg_restore --list < "$TARGET/db.dump" > "$TARGET/db.toc" \
  || { echo "Дамп не читается, копия удалена" >&2; rm -rf "$TARGET"; exit 1; }

# 2. Файлы, которые лежат не в S3 (кэши, временные загрузки, локальные артефакты).
if [[ "$WITH_FILES" == "1" ]]; then
  echo "→ Том backend_data"
  if $COMPOSE exec -T backend sh -c 'test -d /data' 2>/dev/null; then
    if $COMPOSE exec -T backend sh -c 'tar -C /data -czf - .' > "$TARGET/files.tar.gz" 2>/dev/null && [[ -s "$TARGET/files.tar.gz" ]]; then
      echo "  файлы сохранены"
    else
      rm -f "$TARGET/files.tar.gz"
      echo "  файлы не прочитаны — пропущено (на работоспособность копии БД не влияет)"
    fi
  else
    echo "  контейнер backend не запущен — пропущено"
  fi
fi

# 3. Redis: сессии, очереди RQ и кэш. Восстановление возможно и без него.
if [[ "$WITH_REDIS" == "1" ]]; then
  echo "→ Redis"
  if $COMPOSE exec -T redis sh -c 'redis-cli --no-auth-warning SAVE >/dev/null && cat /data/dump.rdb' > "$TARGET/dump.rdb"; then
    [[ -s "$TARGET/dump.rdb" ]] || rm -f "$TARGET/dump.rdb"
  else
    rm -f "$TARGET/dump.rdb"
    echo "  Redis недоступен — пропущено" >&2
  fi
fi

# 4. Конфигурация. В .env пароль БД и ключ шифрования настроек: без него
#    сохранённые токены и ключи S3 не расшифруются.
if [[ -f .env ]]; then
  cp .env "$TARGET/env.backup"
  chmod 600 "$TARGET/env.backup"
fi

SCHEMA="$( $COMPOSE exec -T postgres sh -c "psql -U '$PG_USER' -d '$PG_DB' -tAc 'select version_num from alembic_version'" 2>/dev/null | tr -d '[:space:]' || true )"
{
  echo "CoreLMS backup"
  echo "created: $(date -Is)"
  echo "database: $PG_DB"
  echo "schema: ${SCHEMA:-unknown}"
  echo "git: $(git rev-parse --short HEAD 2>/dev/null || echo n/a)"
  echo
  echo "files:"
  ( cd "$TARGET" && ls -lh | sed 's/^/  /' )
  echo
  echo "sha256:"
  ( cd "$TARGET" && sha256sum db.dump files.tar.gz dump.rdb 2>/dev/null | sed 's/^/  /' || true )
} > "$TARGET/MANIFEST.txt"
chmod 600 "$TARGET"/* 2>/dev/null || true

# 5. Ротация: оставляем KEEP последних каталогов.
mapfile -t OLD < <(find "$DIR" -maxdepth 1 -type d -name 'corelms-*' | sort | head -n -"$KEEP")
for d in "${OLD[@]:-}"; do
  [[ -n "${d:-}" ]] || continue
  echo "→ Удаляю старую копию $(basename "$d")"
  rm -rf "$d"
done

SIZE="$(du -sh "$TARGET" | cut -f1)"
echo
echo "Готово: $TARGET ($SIZE)"
echo "Копий в $DIR: $(find "$DIR" -maxdepth 1 -type d -name 'corelms-*' | wc -l) из $KEEP"
if [[ -f "$TARGET/env.backup" ]]; then
  echo "Внимание: в $TARGET/env.backup лежат секреты. Храните копию вне сервера и не коммитьте её."
fi
