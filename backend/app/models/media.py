"""Derived browser copies; originals and logical file versions never change."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class AssetRendition(Base):
    __tablename__ = "asset_renditions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_assets.id", ondelete="CASCADE"), index=True)
    source_version: Mapped[int] = mapped_column(Integer)
    source_bucket: Mapped[str] = mapped_column(String(200))
    source_object_key: Mapped[str] = mapped_column(String(1000))
    state: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(200), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint("asset_id", "source_version", name="uq_asset_rendition_version"),
                     Index("ix_asset_rendition_dispatch", "state", "updated_at"))


class AssetThumb(Base):
    """Маленькая картинка-превью для списков файлов.

    Хранится отдельно от renditions: превью нужно даже там, где браузерная
    копия не готовится (фото), и не должно зависеть от длительной перекодировки.
    Версионируется вместе с оригиналом: у новой версии файла — новое превью.
    """
    __tablename__ = "asset_thumbs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_assets.id", ondelete="CASCADE"), index=True)
    source_version: Mapped[int] = mapped_column(Integer)
    source_bucket: Mapped[str] = mapped_column(String(200))
    source_object_key: Mapped[str] = mapped_column(String(1000))
    kind: Mapped[str] = mapped_column(String(10), default="image", server_default="image")
    state: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(200), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint("asset_id", "source_version", name="uq_asset_thumb_version"),
                     Index("ix_asset_thumb_state", "state", "updated_at"))
