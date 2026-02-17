#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/deploy-prod.sh
#
# Requires:
#   - docker + docker compose plugin
#   - root .env present (CORELMS_DOMAIN, ACME_EMAIL, NEXT_PUBLIC_API_BASE_URL, POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD)
#   - backend/.env present

if [ ! -f .env ]; then
  echo ".env not found in project root" >&2
  exit 1
fi

if [ ! -f backend/.env ]; then
  echo "backend/.env not found" >&2
  exit 1
fi

echo "Starting CoreLMS production stack..."
docker compose -f docker-compose.prod.yml up -d --build

echo "Waiting for readiness (through Next proxy)..."
for i in $(seq 1 60); do
  if curl -fsS "${NEXT_PUBLIC_API_BASE_URL%/}/api/backend/health/ready" >/dev/null 2>&1; then
    echo "Ready ✅"
    exit 0
  fi
  sleep 2
done

echo "Not ready in time. Check logs:" >&2
echo "  docker compose -f docker-compose.prod.yml logs -f --tail=200" >&2
exit 1
