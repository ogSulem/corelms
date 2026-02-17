#!/usr/bin/env bash
set -euo pipefail

# Smoke checks for production stack.
# Usage:
#   NEXT_PUBLIC_API_BASE_URL=https://your-domain.com ./scripts/smoke-prod.sh

base="${NEXT_PUBLIC_API_BASE_URL:-}"
if [ -z "$base" ]; then
  echo "NEXT_PUBLIC_API_BASE_URL is required (e.g. https://your-domain.com)" >&2
  exit 1
fi

base="${base%/}"

echo "Checking frontend: ${base}/"
curl -fsS "${base}/" >/dev/null

echo "Checking backend readiness (via Next proxy): ${base}/api/backend/health/ready"
curl -fsS "${base}/api/backend/health/ready" >/dev/null

echo "OK"
