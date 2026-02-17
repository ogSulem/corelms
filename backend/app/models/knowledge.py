import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(400), index=True)
    content: Mapped[str] = mapped_column(String, default="")
    tags: Mapped[str | None] = mapped_column(String, nullable=True)

    linked_skills: Mapped[str | None] = mapped_column(String, nullable=True)
    linked_modules: Mapped[str | None] = mapped_column(String, nullable=True)
