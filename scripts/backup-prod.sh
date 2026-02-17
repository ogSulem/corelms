#!/usr/bin/env bash
set -euo pipefail

# Create Postgres + Redis + MinIO volume backups for docker-compose.prod.yml.
# Usage:
#   ./scripts/backup-prod.sh
# Output:
#   backups/<timestamp>/{postgres.dump, redis.rdb, minio.tar.gz}

ts="$(date -u +%Y%m%dT%H%M%SZ)"
outdir="backups/${ts}"
mkdir -p "$outdir"

echo "Backing up Postgres (custom format dump)..."
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U "${POSTGRES_USER:-corelms}" -d "${POSTGRES_DB:-corelms}" -Fc > "${outdir}/postgres.dump"

echo "Saving Redis snapshot (best-effort)..."
# Trigger snapshot; if Redis is configured without persistence this will still produce a file but may be empty.
docker compose -f docker-compose.prod.yml exec -T redis redis-cli save >/dev/null 2>&1 || true
# Copy RDB from container
rid="$(docker compose -f docker-compose.prod.yml ps -q redis)"
if [ -n "$rid" ]; then
  docker cp "${rid}:/data/dump.rdb" "${outdir}/redis.dump.rdb" >/dev/null 2>&1 || true
fi

echo "Archiving MinIO volume (minio_data)..."
# Requires 'tar' inside helper container; uses a throwaway Alpine container.
docker run --rm \
  -v corelms_minio_data:/data:ro \
  -v "$(pwd)/${outdir}:/out" \
  alpine:3.19 sh -c "cd /data && tar -czf /out/minio-data.tar.gz ."

echo "Done: ${outdir}"

echo "IMPORTANT: store backups off-server."
