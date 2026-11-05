import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


from app.core.timeutil import utcnow

class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserTagMap(Base):
    __tablename__ = "user_tag_map"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tags.id"), primary_key=True)

    # Пара (user_id, tag_id) уникальна самим составным ключом. Отдельные индексы
    # нужны для обратных выборок «кто с этим тегом» и «теги пользователя».
    __table_args__ = (
        Index("ix_user_tag_map_user_id", "user_id"),
        Index("ix_user_tag_map_tag_id", "tag_id"),
    )


class ModuleTagMap(Base):
    __tablename__ = "module_tag_map"

    module_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("modules.id"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tags.id"), primary_key=True)

    __table_args__ = (
        Index("ix_module_tag_map_module_id", "module_id"),
        Index("ix_module_tag_map_tag_id", "tag_id"),
    )
