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

import logging

from botocore.exceptions import HTTPClientError, IncompleteReadError, ResponseStreamingError

log = logging.getLogger(__name__)

INTERRUPTED = (HTTPClientError, IncompleteReadError, ResponseStreamingError)


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
