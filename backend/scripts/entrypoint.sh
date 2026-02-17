#!/usr/bin/env sh
set -e

export PYTHONPATH=/app

# Wait for Postgres
python - <<'PY'
import os
import time
import psycopg

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL is required")

# DATABASE_URL is used by SQLAlchemy/Alembic and may include a dialect prefix like
# 'postgresql+psycopg://'. psycopg.connect expects 'postgresql://'.
psycopg_url = url.replace("postgresql+psycopg://", "postgresql://")

for i in range(60):
    try:
        with psycopg.connect(psycopg_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        print("Postgres is ready")
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("Postgres not ready")
PY

# Run migrations
alembic upgrade head

# Wait for MinIO readiness (best-effort)
python - <<'PY'
import os
import time
import urllib.request

url = os.environ.get("S3_ENDPOINT_URL", "http://minio:9000").rstrip("/") + "/minio/health/ready"
for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            if r.status == 200:
                print("MinIO is ready")
                break
    except Exception:
        time.sleep(1)
else:
    print("MinIO not ready yet; continuing")
PY

# Ensure MinIO bucket exists
python - <<'PY'
from app.services.storage import ensure_bucket_exists
ensure_bucket_exists()
print("MinIO bucket ensured")
PY

if [ "${CORELMS_AUTO_SEED:-0}" = "1" ]; then
  if [ ! -f "/data/.seeded" ]; then
    echo "Seeding Start module + users..."
    python /app/scripts/import_start_module.py
    mkdir -p /data
    touch /data/.seeded
  else
    echo "Seed already done"

    python - <<'PY'
import os
import subprocess

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.module import Module, Submodule

with SessionLocal() as db:
    m = db.scalar(select(Module).where(Module.title == "Старт"))
    if m is None:
        raise SystemExit(0)

    cnt = db.query(Submodule).filter(Submodule.module_id == m.id).count()
    if cnt == 0:
        subprocess.check_call(["python", "/app/scripts/import_start_module.py", "--path", "/__missing__"])
PY

    if [ ! -f "/data/.folder_seeded" ]; then
      python - <<'PY'
import pathlib
import subprocess

root = pathlib.Path("/app/Модули обучения")
if not root.exists() or not root.is_dir():
    raise SystemExit(0)

subprocess.check_call(["python", "/app/scripts/import_modules_from_folder.py", "--root", str(root), "--skip-existing"])
PY
      mkdir -p /data
      touch /data/.folder_seeded
    fi
  fi
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
