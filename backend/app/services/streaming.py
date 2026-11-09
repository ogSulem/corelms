"""Отдача файлов из S3 по частям.

Один общий генератор на все потоки (`/assets/{id}/stream`, `/quickstart/stream`),
потому что ошибки здесь одинаковые и одинаково неприятные:

* если клиент ушёл (закрыл вкладку, моргнул мобильный интернет), тело ответа
  закрывается на середине. `body.close()` у botocore на недочитанном потоке
  выбрасывает `IncompleteReadError`, а Starlette показывает его как
  `ResponseStreamingError` → 500 уже после того, как ответ ушёл клиенту. В проде
  это давало «серверную ошибку» `/assets/…/stream` на ровном месте;
* если поток не закрыть вообще, соединение с S3 висит до сборки мусора — при
  большом видео это заметная утечка.
"""
from __future__ import annotations

import asyncio
import logging

from botocore.exceptions import HTTPClientError, IncompleteReadError, ResponseStreamingError
from starlette.requests import ClientDisconnect

log = logging.getLogger(__name__)

INTERRUPTED = (HTTPClientError, IncompleteReadError, ResponseStreamingError)

# Всё, что означает «соединение оборвалось», а не «сервер сломался».
# `ClientDisconnect` приходит из Starlette, остальное — из botocore, сокета и
# asyncio; в Starlette такие ошибки часто приходят завёрнутыми в ExceptionGroup.
DISCONNECTS = (
    *INTERRUPTED,
    ClientDisconnect,
    ConnectionResetError,
    BrokenPipeError,
    asyncio.IncompleteReadError,
)


def is_stream_interrupted(exc: BaseException | None) -> bool:
    """Обрыв соединения во время отдачи файла: это не серверная ошибка.

    Нужен на выходе из приложения: один и тот же обрыв приходит то как
    `ResponseStreamingError`, то как `ClientDisconnect`, то как
    `ExceptionGroup` из `anyio`, и каждый такой случай раньше попадал в журнал
    ошибок как 500 — администратор искал поломку там, где её нет.
    """
    stack: list[BaseException | None] = [exc]
    seen = 0
    while stack and seen < 64:
        current = stack.pop()
        seen += 1
        if current is None:
            continue
        if isinstance(current, DISCONNECTS):
            return True
        if isinstance(current, BaseExceptionGroup):
            stack.extend(current.exceptions)
            continue
        stack.extend((current.__cause__, current.__context__))
    return False


def iter_s3_body(body, chunk_size: int = 512 * 1024):
    """Итерировать тело объекта S3, закрыв его при любом исходе."""
    try:
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            yield chunk
    except INTERRUPTED:
        # Обрыв на стороне клиента или хранилища — штатное завершение, не 500.
        log.debug("s3 stream interrupted", exc_info=True)
    finally:
        try:
            body.close()
        except INTERRUPTED:
            log.debug("s3 stream close after interrupt", exc_info=True)
        except Exception:  # закрытие не должно ломать уже отданный ответ
            log.debug("s3 stream close failed", exc_info=True)
