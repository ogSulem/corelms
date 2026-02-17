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

s3 = os.environ.get("S3_ENDPOINT_URL", "http://minio:9000").rstrip("/")

# Only MinIO exposes /minio/health/ready. For real S3 (REG.RU, AWS, etc.) skip this probe.
if "minio" not in s3:
    print("MinIO readiness probe skipped")
    raise SystemExit(0)

url = s3 + "/minio/health/ready"
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
  echo "Checking seed state in DB..."
  python - <<'PY'
import os
import subprocess

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.module import Module, Submodule
from app.models.user import User

admin_name = os.environ.get("CORELMS_SEED_ADMIN_NAME", "admin")

with SessionLocal() as db:
    has_admin = db.scalar(select(User).where(User.name == admin_name)) is not None
    m = db.scalar(select(Module).where(Module.title == "Старт"))
    has_start = m is not None
    has_start_lessons = False
    if m is not None:
        has_start_lessons = db.query(Submodule).filter(Submodule.module_id == m.id).count() > 0

if not has_admin or not has_start or not has_start_lessons:
    print("Seeding Start module + users...", flush=True)
    subprocess.check_call(["python", "/app/scripts/import_start_module.py"])
else:
    print("Seed already present; skipping", flush=True)
PY
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
