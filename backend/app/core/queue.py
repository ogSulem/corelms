from __future__ import annotations

import redis
from rq import Queue
from rq.job import Job

from app.core.config import settings


def get_queue(name: str | None = None) -> Queue:
    conn = redis.Redis.from_url(settings.redis_url)
    eff = str(name or "").strip() or str(settings.rq_queue_default)
    return Queue(name=eff, connection=conn)


def fetch_job(job_id: str) -> Job | None:
    try:
        conn = redis.Redis.from_url(settings.redis_url)
        return Job.fetch(job_id, connection=conn)
    except Exception:
        return None
