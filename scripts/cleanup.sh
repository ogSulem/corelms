#!/usr/bin/env bash
set -euo pipefail

echo "CoreLMS cleanup starting..."

rm -rf \
  frontend/node_modules \
  frontend/.next \
  frontend/out \
  backend/.pytest_cache \
  backend/.venv \
  .pytest_cache \
  .venv \
  backend/**/__pycache__ \
  backend/app/**/__pycache__ \
  backend/scripts/**/__pycache__ \
  backend/tests/**/__pycache__ \
  2>/dev/null || true

# Safer __pycache__ cleanup
find backend -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true

echo "Done."
