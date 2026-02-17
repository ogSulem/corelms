import uuid

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SubmoduleAssetMap(Base):
    __tablename__ = "submodule_asset_map"

    submodule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submodules.id"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_assets.id"), primary_key=True
    )

    order: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (UniqueConstraint("submodule_id", "order", name="uq_submodule_asset_order"),)
