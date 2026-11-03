from __future__ import annotations

from rq import Queue
from rq.job import Job
from rq.exceptions import NoSuchJobError

from app.core.config import settings
from app.core.redis_client import get_redis_rq


def get_queue(name: str | None = None) -> Queue:
    eff = str(name or "").strip() or str(settings.rq_queue_default)
    return Queue(name=eff, connection=get_redis_rq())


def fetch_job(job_id: str, *, strict: bool = False) -> Job | None:
    try:
        return Job.fetch(job_id, connection=get_redis_rq())
    except NoSuchJobError:
        return None
    except Exception:
        if strict:
            raise
        return None


def normalize_job_status(value) -> str:
    """RQ 1.16 returns a str Enum; str(enum) is 'JobStatus.STARTED'."""
    return str(getattr(value, "value", value) or "").rsplit(".", 1)[-1].strip().lower()


def get_job_status(job, *, refresh: bool = True) -> str:
    return normalize_job_status(job.get_status(refresh=refresh))


def release_job_lock(connection, key: str, job_id: str) -> None:
    """Never release a newer job's lease when an older worker finishes."""
    connection.eval(
        "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
        1, key, str(job_id),
    )
