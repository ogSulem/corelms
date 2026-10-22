"""Learning achievements are independent of the current content revision."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ModuleCompletion(Base):
    __tablename__ = "module_completions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    module_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    content_revision: Mapped[int] = mapped_column(Integer, default=1)


class LessonQuizVersion(Base):
    """Keep the link to previous quizzes, including all attempts and answers."""
    __tablename__ = "lesson_quiz_versions"

    quiz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quizzes.id"), primary_key=True)
    submodule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("submodules.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
