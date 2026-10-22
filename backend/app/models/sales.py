"""Sales library metadata. Legacy S3 paths are adopted lazily, never deleted."""
import uuid
from sqlalchemy import Boolean, ForeignKey, Integer, String, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class SalesSection(Base):
    __tablename__ = "sales_sections"
    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class SalesEntry(Base):
    __tablename__ = "sales_entries"
    __table_args__ = (Index("ix_sales_entries_directory", "section", "path", "is_archived"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section: Mapped[str] = mapped_column(String(20), ForeignKey("sales_sections.name"), index=True)
    path: Mapped[str] = mapped_column(String(1000), default="")
    name: Mapped[str] = mapped_column(String(400))
    identity_key: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(10))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("content_assets.id"), unique=True, nullable=True)
    legacy_key: Mapped[str | None] = mapped_column(String(1000), unique=True, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
