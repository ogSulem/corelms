from __future__ import annotations

import os
import redis
from rq import Connection, Worker

from app.core.config import settings


def main() -> None:
    conn = redis.Redis.from_url(settings.redis_url)
    raw = str(os.getenv("RQ_WORKER_QUEUES") or "").strip()
    if raw:
        queues = [q.strip() for q in raw.split(",") if q.strip()]
    else:
        queues = [
            str(settings.rq_queue_import),
            str(settings.rq_queue_regen),
            str(settings.rq_queue_default),
        ]
    with Connection(conn):
        worker = Worker(queues)
        worker.work()


if __name__ == "__main__":
    main()
