"""Immutable snapshots of lesson text; independent of quiz/asset versions."""
from datetime import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LessonRevision(Base):
    __tablename__ = "lesson_revisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submodule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("submodules.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, default="")
    content_mode: Mapped[str] = mapped_column(String(16), default="manual")
    content_object_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (UniqueConstraint("submodule_id", "version", name="uq_lesson_revision"),)
