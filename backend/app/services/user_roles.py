"""Какую роль обучающегося реально принимает база.

Платформа работает полгода, и тип `userrole` в её базе пришёл из более ранней
схемы: там обучающиеся назывались `partner`, а значения `employee` не было
вовсе. Миграции добавляли значения по списку «своего» времени (`0008` — employee
и admin, `0020` — superadmin, `0025` — partner), поэтому отсутствующее значение
так и осталось отсутствующим. Следствие видно в журнале ошибок:

    DataError: invalid input value for enum userrole: "employee"
    INSERT INTO users (... role ...)

То есть «Добавить партнёра» не могло сработать вообще никогда: форма всегда
создавала учётную запись с ролью `employee`, которой в базе нет.

Правило выбора роли здесь такое: **та, что уже используется в данных**. На
рабочей базе это `partner` (все 88 обучающихся), на чистой — `employee`, как и
задумано в коде. Так новый человек не оказывается единственным с другим именем
роли: отчёты и фильтры, где встречается `role = 'partner'`, продолжают считать
всех. Если прочитать схему не удалось (SQLite в тестах), ничего не меняем.

Миграция `0030` добавляет недостающие значения в тип, но код не должен зависеть
от того, применена ли она уже.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.user import UserRole

log = logging.getLogger(__name__)

# Порядок предпочтения на чистой базе: employee — «каноническое» имя роли
# обучающегося, partner — историческое имя той же роли в рабочих данных.
LEARNER_ROLES: tuple[UserRole, ...] = (UserRole.employee, UserRole.partner)

# Кэш на процесс: тип enum и набор ролей в данных между запросами не меняются,
# а лишние запросы на каждое создание пользователя не нужны. Минута — чтобы
# после миграции правка подхватилась без перезапуска контейнера.
_CACHE_TTL_SECONDS = 60.0
_cache: dict[str, object] = {"labels": None, "labels_at": 0.0, "in_use": None, "in_use_at": 0.0}


def clear_cache() -> None:
    _cache.update({"labels": None, "labels_at": 0.0, "in_use": None, "in_use_at": 0.0})


def _fresh(key: str) -> bool:
    return time.monotonic() - float(_cache.get(f"{key}_at") or 0.0) < _CACHE_TTL_SECONDS


def schema_role_labels(db: Session) -> set[str]:
    """Значения типа `userrole` в текущей базе. Пусто — «ограничений не знаем»."""
    cached = _cache.get("labels")
    if isinstance(cached, set) and _fresh("labels"):
        return set(cached)

    labels: set[str] = set()
    try:
        if db.get_bind().dialect.name == "postgresql":
            rows = db.execute(text("select unnest(enum_range(null::userrole))::text")).scalars().all()
            labels = {str(row).strip().lower() for row in rows if str(row or "").strip()}
    except Exception:
        # Типа нет или база не PostgreSQL (тесты на SQLite) — работаем как раньше.
        log.debug("userrole: could not read enum labels", exc_info=True)
        labels = set()

    _cache.update({"labels": labels, "labels_at": time.monotonic()})
    return set(labels)


def used_learner_roles(db: Session) -> dict[str, int]:
    """Какие учебные роли реально встречаются в данных — по убыванию частоты.

    `role::text` обязателен: сравнение с литералом, которого нет в типе enum,
    само по себе падает с «invalid input value for enum».
    """
    cached = _cache.get("in_use")
    if isinstance(cached, dict) and _fresh("in_use"):
        return dict(cached)

    counts: dict[str, int] = {}
    try:
        if db.get_bind().dialect.name == "postgresql":
            rows = db.execute(text("select role::text as role, count(*) as n from users group by 1")).all()
            learner_values = {role.value for role in LEARNER_ROLES}
            counts = {
                str(role).strip().lower(): int(n)
                for role, n in rows
                if str(role or "").strip().lower() in learner_values
            }
    except Exception:
        log.debug("userrole: could not read roles in use", exc_info=True)
        counts = {}

    _cache.update({"in_use": counts, "in_use_at": time.monotonic()})
    return dict(counts)


def pick_learner_role(labels: set[str], in_use: dict[str, int] | None = None) -> UserRole:
    """Роль для новой учебной учётной записи.

    Сначала — то, что уже используется в данных (иначе новый человек окажется
    единственным «employee» в базе из «partner»), затем — первая доступная по
    порядку предпочтения. Если схема неизвестна, возвращаем каноническую роль.
    """
    if not labels:
        return UserRole.employee

    for role, _count in sorted((in_use or {}).items(), key=lambda item: (-item[1], item[0])):
        if role in labels:
            return UserRole(role)

    for candidate in LEARNER_ROLES:
        if candidate.value in labels:
            return candidate

    # В типе нет ни одной учебной роли — пусть скажет база, а не мы молча.
    return UserRole.employee


def learner_role(db: Session) -> UserRole:
    """Роль для новой учебной учётной записи в этой базе."""
    role = pick_learner_role(schema_role_labels(db), used_learner_roles(db))
    if role is not UserRole.employee:
        log.info("userrole: creating learners as %r, as this database already does", role.value)
    return role


def resolve_role(db: Session, role: UserRole) -> UserRole:
    """Привести запрошенную роль к той, что примет база.

    Если явно запрошенную роль тип принимает — оставляем её как есть (суперадмин
    вправе назвать роль `partner` или `employee`). Подмена нужна только тогда,
    когда такого значения в базе вовсе нет.
    """
    labels = schema_role_labels(db)
    if not labels or role.value in labels:
        return role
    if role in LEARNER_ROLES:
        return learner_role(db)
    return role
