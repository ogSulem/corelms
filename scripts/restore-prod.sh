#!/usr/bin/env bash
set -euo pipefail

# Restore Postgres and MinIO from a backup directory produced by backup-prod.sh.
# Usage:
#   ./scripts/restore-prod.sh backups/<timestamp>
#
# This script is intentionally explicit and will stop on errors.

bdir="${1:-}"
if [ -z "$bdir" ] || [ ! -d "$bdir" ]; then
  echo "Usage: ./scripts/restore-prod.sh backups/<timestamp>" >&2
  exit 1
fi

pgdump="${bdir}/postgres.dump"
miniotar="${bdir}/minio-data.tar.gz"

if [ ! -f "$pgdump" ]; then
  echo "Missing ${pgdump}" >&2
  exit 1
fi
if [ ! -f "$miniotar" ]; then
  echo "Missing ${miniotar}" >&2
  exit 1
fi

echo "Stopping stack (keeps volumes)..."
docker compose -f docker-compose.prod.yml down

echo "Starting Postgres only..."
docker compose -f docker-compose.prod.yml up -d postgres

echo "Waiting for Postgres..."
for i in $(seq 1 60); do
  if docker compose -f docker-compose.prod.yml exec -T postgres pg_isready -U "${POSTGRES_USER:-corelms}" -d "${POSTGRES_DB:-corelms}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
  if [ "$i" = "60" ]; then
    echo "Postgres not ready" >&2
    exit 1
  fi
done

echo "Dropping and recreating database..."
docker compose -f docker-compose.prod.yml exec -T postgres psql -U "${POSTGRES_USER:-corelms}" -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${POSTGRES_DB:-corelms}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "${POSTGRES_DB:-corelms}";
CREATE DATABASE "${POSTGRES_DB:-corelms}";
SQL

echo "Restoring Postgres dump..."
docker compose -f docker-compose.prod.yml exec -T postgres pg_restore -U "${POSTGRES_USER:-corelms}" -d "${POSTGRES_DB:-corelms}" --clean --if-exists < "$pgdump"

echo "Restoring MinIO volume (minio_data)..."
# Wipe volume contents then extract tarball.
docker run --rm \
  -v corelms_minio_data:/data \
  -v "$(pwd)/${bdir}:/in" \
  alpine:3.19 sh -c "rm -rf /data/* && mkdir -p /data && tar -xzf /in/minio-data.tar.gz -C /data"

echo "Starting full stack..."
docker compose -f docker-compose.prod.yml up -d

echo "Done."
