"""Обрыв потока файла не должен становиться 500.

В проде это уже случилось: ученик смотрел видео, соединение моргнуло — и в журнал
ошибок падала «серверная ошибка» `/assets/…/stream` с `IncompleteRead`. Причина не
в S3, а в том, как закрывалось тело: клиент уходил, генератор закрывался, а
`body.close()` на недочитанном потоке выбрасывал исключение уже после начала
ответа. Starlette показывал его как `ResponseStreamingError`.

Проверяем оба пути: обрыв при чтении и обрыв при закрытии. Тот же генератор
используют `/assets/{id}/stream` и `/quickstart/stream`.
"""
from __future__ import annotations

from botocore.exceptions import IncompleteReadError, ResponseStreamingError

from app.services.streaming import iter_s3_body


class _Body:
    def __init__(self, chunks, fail_read=False, fail_close=False):
        self.chunks = list(chunks)
        self.fail_read = fail_read
        self.fail_close = fail_close
        self.closed = False

    def read(self, size):
        if self.chunks:
            return self.chunks.pop(0)
        if self.fail_read:
            raise ResponseStreamingError(error="connection broken")
        return b""

    def close(self):
        self.closed = True
        if self.fail_close:
            raise IncompleteReadError(actual_bytes=1, expected_bytes=2)


def test_read_interrupt_ends_stream_quietly():
    body = _Body([b"a" * 10, b"b" * 10], fail_read=True)
    assert list(iter_s3_body(body)) == [b"a" * 10, b"b" * 10]
    assert body.closed is True


def test_close_interrupt_after_client_leaves_is_quiet():
    body = _Body([b"a" * 10, b"b" * 10], fail_close=True)
    stream = iter_s3_body(body)
    assert next(stream) == b"a" * 10
    stream.close()  # клиент закрыл вкладку: приходит GeneratorExit
    assert body.closed is True


def test_normal_stream_returns_everything():
    body = _Body([b"x", b"y"])
    assert list(iter_s3_body(body)) == [b"x", b"y"]
    assert body.closed is True


def test_chunk_size_is_respected():
    calls: list[int] = []

    class Body(_Body):
        def read(self, size):
            calls.append(size)
            return super().read(size)

    list(iter_s3_body(Body([b"a"]), chunk_size=1024))
    assert calls and all(size == 1024 for size in calls)


def test_both_streaming_endpoints_use_the_shared_helper():
    """Ни один поток не должен снова обзавестись своим генератором без закрытия."""
    import inspect

    from app.routers import assets as assets_router
    from app.routers import quickstart as quickstart_router

    for module in (assets_router, quickstart_router):
        source = inspect.getsource(module)
        assert "iter_s3_body(" in source, module.__name__
        assert "def _body_iter(" not in source, module.__name__
        assert "def _stream_body_iter(" not in source, module.__name__
