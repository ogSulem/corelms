import enum
import logging
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRole(str, enum.Enum):
    employee = "employee"
    admin = "admin"
    superadmin = "superadmin"
    # В базе полугодовалой давности встречается роль partner. Приложение её
    # раньше не знало и падало на любом чтении пользователей:
    # LookupError: 'partner' is not among the defined enum values.
    partner = "partner"


class RoleEnum(PgEnum):
    """Enum ролей, устойчивый к значениям, которых нет в коде.

    Если в базе окажется незнакомая роль (её мог добавить SQL-скрипт или старая
    версия), чтение пользователей не должно падать с 500 на весь список.
    Такая роль трактуется как «без административных прав».

    Наследуемся от постгресового ENUM, потому что на PostgreSQL SQLAlchemy
    подменяет обычный Enum его диалектной копией и переопределение теряется.
    SQLite при этом тоже работает: тип рендерится как VARCHAR с CHECK.
    """

    def _object_value_for_elem(self, elem):
        try:
            return super()._object_value_for_elem(elem)
        except LookupError:
            logging.getLogger("corelms").warning(
                "unknown user role %r in database; treated as employee", elem
            )
            return UserRole.employee


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), index=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    role: Mapped[UserRole] = mapped_column(RoleEnum(UserRole), index=True)
    position: Mapped[str | None] = mapped_column(String(200), nullable=True)

    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    xp: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    streak: Mapped[int] = mapped_column(Integer, default=0)

    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    password_hash: Mapped[str] = mapped_column(String(255))

    must_change_password: Mapped[bool] = mapped_column(default=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
