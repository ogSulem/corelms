#!/usr/bin/env bash
# Восстановление CoreLMS из копии, сделанной scripts/backup.sh.
#
#   ./scripts/restore.sh backups/corelms-2026-10-27_03-30-00 --yes
#   ./scripts/restore.sh backups/corelms-... --yes --with-files --with-redis
#
# Что делает:
#   1) проверяет, что дамп читается (pg_restore --list);
#   2) снимает свежую копию текущего состояния (отключается --no-safety-backup);
#   3) останавливает API и воркеры, чтобы никто не писал в базу;
#   4) заливает дамп: pg_restore --clean --if-exists --no-owner;
#   5) поднимает сервисы и печатает текущую версию схемы.
#
# Это разрушающая операция: данные, появившиеся после копии, будут потеряны.
# Файлы S3 этим скриптом не трогаются вообще.
set -Eeuo pipefail

COMPOSE="${COMPOSE:-docker compose}"
SRC=""
CONFIRM=0
WITH_FILES=0
WITH_REDIS=0
SAFETY=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) CONFIRM=1; shift ;;
    --with-files) WITH_FILES=1; shift ;;
    --with-redis) WITH_REDIS=1; shift ;;
    --no-safety-backup) SAFETY=0; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    -*) echo "Неизвестный параметр: $1" >&2; exit 2 ;;
    *) SRC="$1"; shift ;;
  esac
done

cd "$(dirname "$0")/.."
[[ -f docker-compose.yml ]] || { echo "Нет docker-compose.yml рядом со скриптом" >&2; exit 1; }
[[ -n "$SRC" ]] || { echo "Укажите каталог копии: ./scripts/restore.sh backups/corelms-... --yes" >&2; exit 2; }
[[ -s "$SRC/db.dump" ]] || { echo "В $SRC нет db.dump" >&2; exit 1; }

if [[ "$CONFIRM" != "1" ]]; then
  cat >&2 <<'MSG'
Это восстановление заменит текущую базу данными из копии.
Всё, что появилось после копии, будет потеряно. Ничего не изменено: добавьте --yes, если уверены.
MSG
  exit 3
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
PG_DB="${POSTGRES_DB:-sdlp}"
PG_USER="${POSTGRES_USER:-sdlp}"

echo "→ Проверяю дамп"
$COMPOSE exec -T postgres pg_restore --list < "$SRC/db.dump" > /dev/null \
  || { echo "Дамп не читается — восстановление остановлено, ничего не изменено" >&2; exit 1; }

if [[ "$SAFETY" == "1" ]]; then
  echo "→ Копия текущего состояния перед восстановлением"
  ./scripts/backup.sh --dir ./backups --no-files || echo "  предупредительная копия не создана — продолжаем по вашему решению"
fi

echo "→ Останавливаю API и воркеры"
$COMPOSE stop backend worker_import worker_regen worker_default worker_media >/dev/null

echo "→ Восстанавливаю базу $PG_DB"
$COMPOSE exec -T postgres pg_restore -U "$PG_USER" -d "$PG_DB" --clean --if-exists --no-owner < "$SRC/db.dump"

if [[ "$WITH_FILES" == "1" && -s "$SRC/files.tar.gz" ]]; then
  echo "→ Восстанавливаю том backend_data"
  $COMPOSE run --rm --no-deps -T --entrypoint sh backend -c 'tar -C /data -xzf -' < "$SRC/files.tar.gz"
fi

if [[ "$WITH_REDIS" == "1" && -s "$SRC/dump.rdb" ]]; then
  echo "→ Восстанавливаю Redis (сессии и очереди)"
  $COMPOSE stop redis >/dev/null
  $COMPOSE run --rm --no-deps -T --entrypoint sh redis -c 'cat > /data/dump.rdb' < "$SRC/dump.rdb"
  $COMPOSE start redis >/dev/null
fi

echo "→ Поднимаю сервисы"
$COMPOSE up -d backend worker_import worker_regen worker_default worker_media frontend >/dev/null

SCHEMA="$( $COMPOSE exec -T postgres sh -c "psql -U '$PG_USER' -d '$PG_DB' -tAc 'select version_num from alembic_version'" 2>/dev/null | tr -d '[:space:]' || true )"
echo "→ Схема после восстановления: ${SCHEMA:-не определена}"
echo "→ Проверьте: curl -fsS http://127.0.0.1:8080/api/health/ready"
echo "→ Откройте «Админ-центр → Настройки»: версия схемы и состояние S3 должны совпасть с копией."
if [[ -f "$SRC/env.backup" ]]; then
  echo
  echo "В копии есть $SRC/env.backup. Если менялись JWT_SECRET_KEY или SETTINGS_ENCRYPTION_KEY,"
  echo "верните прежние значения — иначе сохранённые токен AI и ключи S3 не расшифруются."
fi
