import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContentAsset(Base):
    __tablename__ = "content_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    module_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("modules.id"), nullable=True, index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    source_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    bucket: Mapped[str] = mapped_column(String(200))
    object_key: Mapped[str] = mapped_column(String(1000), unique=True, index=True)

    original_filename: Mapped[str] = mapped_column(String(400))
    mime_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class AssetRevision(Base):
    """Immutable previous file versions. Never overwrite an object in storage."""
    __tablename__ = "asset_revisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_assets.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    bucket: Mapped[str] = mapped_column(String(200))
    object_key: Mapped[str] = mapped_column(String(1000))
    original_filename: Mapped[str] = mapped_column(String(400))
    mime_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (UniqueConstraint("asset_id", "version", name="uq_asset_revision"),)
