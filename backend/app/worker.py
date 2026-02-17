from __future__ import annotations

import redis
from rq import Connection, Worker

from app.core.config import settings


def main() -> None:
    conn = redis.Redis.from_url(settings.redis_url)
    with Connection(conn):
        worker = Worker(["corelms"])
        worker.work()


if __name__ == "__main__":
    main()
