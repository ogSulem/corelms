from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import logging

import multiprocessing

import psycopg
import redis
from alembic import command
from alembic.config import Config
from rq import Connection, Worker
from sqlalchemy import create_engine, text


log = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    v = str(os.getenv(name) or "").strip()
    if not v:
        raise SystemExit(f"{name} is required")
    return v


def _wait_postgres(*, database_url: str, timeout_s: int = 60) -> None:
    psycopg_url = database_url.replace("postgresql+psycopg://", "postgresql://")
    deadline = time.time() + max(1, int(timeout_s))
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with psycopg.connect(psycopg_url, connect_timeout=2) as conn:
                conn.execute("select 1")
            return
        except Exception as e:
            last_err = e
            time.sleep(1)
    raise SystemExit(f"Postgres not ready: {last_err}")


def _run_migrations(*, database_url: str) -> None:
    root = Path(__file__).resolve().parents[1]
    cfg_path = root / "alembic.ini"
    alembic_cfg = Config(str(cfg_path))
    alembic_cfg.set_main_option("script_location", str(root / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", str(database_url))

    engine = create_engine(str(database_url), pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("select pg_advisory_lock(hashtext('corelms_alembic'))"))
        try:
            command.upgrade(alembic_cfg, "head")
        finally:
            conn.execute(text("select pg_advisory_unlock(hashtext('corelms_alembic'))"))


def _ensure_bucket() -> None:
    from app.services.storage import ensure_bucket_exists

    ensure_bucket_exists()


def _start_worker(*, redis_url: str, queues: list[str]) -> None:
    def _run_one() -> None:
        conn = redis.Redis.from_url(redis_url)
        with Connection(conn):
            worker = Worker(queues)
            worker.work()

    try:
        procs = int(os.getenv("RQ_WORKER_PROCESSES") or "1")
    except Exception:
        procs = 1
    procs = max(1, min(procs, 16))

    if procs <= 1:
        _run_one()
        return

    children: list[multiprocessing.Process] = []
    for i in range(procs):
        p = multiprocessing.Process(target=_run_one, name=f"rq-worker-{i+1}")
        p.daemon = False
        p.start()
        children.append(p)

    # Wait for the first worker process to exit; if any exits, terminate all.
    try:
        while True:
            for p in children:
                p.join(timeout=0.5)
                if not p.is_alive():
                    raise SystemExit(p.exitcode or 0)
    finally:
        for p in children:
            try:
                if p.is_alive():
                    p.terminate()
            except Exception:
                log.debug("failed to terminate worker process", exc_info=True)


def main(argv: list[str] | None = None) -> None:
    from app.core.config import settings

    logger = logging.getLogger("corelms.launcher")
    p = argparse.ArgumentParser(prog="corelms")
    p.add_argument("mode", choices=["api", "worker"], help="api or worker")
    args = p.parse_args(argv)

    database_url = settings.database_url
    redis_url = settings.redis_url

    _wait_postgres(database_url=database_url, timeout_s=int(os.getenv("CORELMS_WAIT_DB_TIMEOUT_S") or "60"))

    if settings.auto_migrate_on_start:
        _run_migrations(database_url=database_url)

    s3_endpoint = settings.s3_endpoint_url
    if s3_endpoint:
        try:
            _ensure_bucket()
        except Exception:
            logger.warning("S3 bucket ensure failed during startup; continuing")

    if args.mode == "api":
        import uvicorn

        host = str(os.getenv("HOST") or "0.0.0.0")
        port = int(os.getenv("PORT") or "8000")
        try:
            workers = int(os.getenv("UVICORN_WORKERS") or "1")
        except Exception:
            workers = 1
        workers = max(1, min(workers, 16))
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            log_level=str(os.getenv("LOG_LEVEL") or "info"),
            workers=workers,
        )
        return

    raw = str(os.getenv("RQ_WORKER_QUEUES") or "").strip()
    if raw:
        queues = [q.strip() for q in raw.split(",") if q.strip()]
    else:
        from app.core.config import settings

        queues = [
            str(settings.rq_queue_import),
            str(settings.rq_queue_regen),
            str(settings.rq_queue_cleanup),
            str(settings.rq_queue_default),
        ]

    _start_worker(redis_url=redis_url, queues=queues)


if __name__ == "__main__":
    main(sys.argv[1:])
