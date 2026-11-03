from __future__ import annotations

from functools import lru_cache

import redis

from app.core.config import settings

_TIMEOUTS = {"socket_connect_timeout": 3, "socket_timeout": 3}


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Общий клиент для приложения: строки вместо байтов.

    Один экземпляр и один пул соединений на процесс. Раньше часть кода создавала
    `redis.Redis.from_url(...)` на каждый вызов — например, при опросе списка
    задач импорта это были десятки новых пулов за один запрос.
    """
    return redis.Redis.from_url(settings.redis_url, decode_responses=True, **_TIMEOUTS)


@lru_cache(maxsize=1)
def get_redis_rq() -> redis.Redis:
    """Клиент для RQ: без `decode_responses`.

    Очереди RQ хранят сериализованные байты, декодирование их ломает. Пул общий
    на процесс: очередь, задача и реестры переиспользуют одни соединения.
    """
    return redis.Redis.from_url(settings.redis_url, **_TIMEOUTS)
