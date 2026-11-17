"""Что именно случилось с базой: разные причины — разные ответы.

Раньше любая ошибка SQLAlchemy (`DBAPIError` — а это и `IntegrityError`, и
`DataError`, и `ProgrammingError`) отдавалась как «База данных перегружена или
недоступна. Повторите запрос через минуту; данные не потеряны». Из-за этого:

* нарушение уникальности (например, такой адрес уже есть) выглядело как
  перегрузка — администратор повторял создание партнёра и получал то же самое;
* слишком длинное значение поля выглядело так же, хотя лечится правкой текста;
* неприменённая миграция (код новее схемы) выглядела как «сервер занят», хотя
  повторы не помогут никогда.

Здесь ошибка раскладывается на три честные группы: «повторите — пройдёт»
(503), «исправьте данные» (409/422) и «сломана конфигурация» (500). Код причины
и SQLSTATE попадают в журнал ошибок администрирования, поэтому по одному
request_id видно причину без SSH.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import (
    DataError,
    DBAPIError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
    TimeoutError as SATimeoutError,
)


@dataclass(frozen=True)
class DbFailure:
    status: int
    code: str
    message: str
    reason: str
    hint: str = ""
    retry_after: int | None = None

    @property
    def retryable(self) -> bool:
        return self.retry_after is not None


POOL_MESSAGE = (
    "Свободных соединений с базой нет: сервер одновременно обрабатывает слишком "
    "много запросов. Повторите через 10–20 секунд — данные не потеряны."
)
UNREACHABLE_MESSAGE = "Нет соединения с базой данных. Повторите через минуту — данные не потеряны."
CONNECTIONS_MESSAGE = "У базы данных закончились свободные подключения. Повторите через минуту — данные не потеряны."
DISK_MESSAGE = "На сервере закончилось место на диске: запись сейчас невозможна. Данные не потеряны, но администратору нужно освободить место."
MEMORY_MESSAGE = "Серверу не хватает памяти для запроса. Повторите через минуту; если повторяется — администратору нужно проверить нагрузку."
RESTART_MESSAGE = "База данных перезапускается. Повторите через минуту — данные не потеряны."
DEADLOCK_MESSAGE = "Запрос столкнулся с другим изменением тех же данных и был отменён. Повторите действие."
TIMEOUT_MESSAGE = "Запрос к базе выполнялся слишком долго и был остановлен. Повторите действие."
CONFLICT_MESSAGE = "Такие данные уже есть в системе либо не хватает связанной записи. Обновите страницу и проверьте поля."
VALUE_MESSAGE = "Значение не подходит по формату или длине. Сократите текст и повторите."
SCHEMA_MESSAGE = (
    "Приложение и база данных разной версии — обновление не завершено. "
    "Повторите через минуту; если ошибка остаётся, сообщите администратору код ниже."
)
GENERIC_MESSAGE = "Ошибка базы данных. Повторите попытку позже."


def _sqlstate(exc: BaseException) -> str:
    orig = getattr(exc, "orig", None)
    for source in (orig, exc):
        for attr in ("pgcode", "sqlstate"):
            value = getattr(source, attr, None)
            if value:
                return str(value).strip().upper()
    return ""


def _text(exc: BaseException) -> str:
    orig = getattr(exc, "orig", None)
    parts = [str(orig or ""), str(exc or "")]
    return " ".join(p for p in parts if p).lower()


def _constraint(exc: BaseException) -> str:
    """Имя ограничения/колонки: по нему видно, ЧТО именно не подошло."""
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    for attr in ("constraint_name", "column_name"):
        value = getattr(diag, attr, None)
        if value:
            return str(value).strip()
    return ""


def _hint(exc: BaseException, *, reason: str) -> str:
    state = _sqlstate(exc)
    orig = getattr(exc, "orig", None)
    detail = str(orig or exc or "").strip().splitlines()
    first = detail[0][:180] if detail else ""
    constraint = _constraint(exc)
    return " | ".join(
        part
        for part in (
            f"причина: {reason}",
            f"SQLSTATE {state}" if state else "",
            f"ограничение: {constraint}" if constraint else "",
            first,
        )
        if part
    )


def classify_db_error(exc: BaseException) -> DbFailure | None:
    """Разобрать ошибку базы. `None` — это не ошибка базы данных."""

    if isinstance(exc, SATimeoutError):
        return DbFailure(503, "database_unavailable", POOL_MESSAGE, "pool_busy",
                         hint=_hint(exc, reason="pool_busy"), retry_after=15)

    if isinstance(exc, InterfaceError):
        return DbFailure(503, "database_unavailable", UNREACHABLE_MESSAGE, "unreachable",
                         hint=_hint(exc, reason="unreachable"), retry_after=15)

    if isinstance(exc, OperationalError):
        state = _sqlstate(exc)
        text = _text(exc)
        if state in {"53300", "53400"} or "too many clients" in text or "remaining connection slots" in text:
            return DbFailure(503, "database_unavailable", CONNECTIONS_MESSAGE, "connections",
                             hint=_hint(exc, reason="connections"), retry_after=20)
        if state in {"53100", "53200"} or "no space left" in text or "disk full" in text:
            if state == "53200" or "out of memory" in text:
                return DbFailure(503, "database_unavailable", MEMORY_MESSAGE, "memory",
                                 hint=_hint(exc, reason="memory"), retry_after=20)
            return DbFailure(503, "database_unavailable", DISK_MESSAGE, "disk",
                             hint=_hint(exc, reason="disk"), retry_after=None)
        if state in {"57P01", "57P02", "57P03", "57P04"} or "starting up" in text or "shutting down" in text:
            return DbFailure(503, "database_unavailable", RESTART_MESSAGE, "restart",
                             hint=_hint(exc, reason="restart"), retry_after=10)
        if state == "40P01" or "deadlock detected" in text:
            return DbFailure(503, "database_unavailable", DEADLOCK_MESSAGE, "deadlock",
                             hint=_hint(exc, reason="deadlock"), retry_after=5)
        if "could not connect" in text or "connection refused" in text or "connection reset" in text:
            return DbFailure(503, "database_unavailable", UNREACHABLE_MESSAGE, "unreachable",
                             hint=_hint(exc, reason="unreachable"), retry_after=15)
        # Сюда попадают пропавшие на полуслове соединения и таймауты TCP.
        return DbFailure(503, "database_unavailable", UNREACHABLE_MESSAGE, "unreachable",
                         hint=_hint(exc, reason="unreachable"), retry_after=15)

    if isinstance(exc, ProgrammingError):
        state = _sqlstate(exc)
        if state == "57014" or "canceling statement" in _text(exc):
            return DbFailure(503, "database_unavailable", TIMEOUT_MESSAGE, "query_timeout",
                             hint=_hint(exc, reason="query_timeout"), retry_after=5)
        return DbFailure(500, "schema_outdated", SCHEMA_MESSAGE, "schema",
                         hint=_hint(exc, reason="schema"))

    if isinstance(exc, IntegrityError):
        return DbFailure(409, "conflict", CONFLICT_MESSAGE, "integrity",
                         hint=_hint(exc, reason="integrity"))

    if isinstance(exc, DataError):
        return DbFailure(422, "invalid_value", VALUE_MESSAGE, "value",
                         hint=_hint(exc, reason="value"))

    if isinstance(exc, DBAPIError):
        return DbFailure(500, "database_error", GENERIC_MESSAGE, "unknown",
                         hint=_hint(exc, reason="unknown"))

    return None
