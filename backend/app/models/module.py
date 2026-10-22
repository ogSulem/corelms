import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Module(Base):
    __tablename__ = "modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(300), index=True)
    description: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    visibility: Mapped[str] = mapped_column(String(20), default="public", index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    content_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    import_object_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    storage_prefix: Mapped[str | None] = mapped_column(String(400), nullable=True)
    final_quiz_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    final_quiz_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("quizzes.id"), nullable=True)


class ModuleSkillMap(Base):
    __tablename__ = "module_skill_map"

    module_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("modules.id"), primary_key=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (UniqueConstraint("module_id", "skill_id", name="uq_module_skill"),)


class Submodule(Base):
    __tablename__ = "submodules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("modules.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(String, default="")
    presentation_mode: Mapped[str] = mapped_column(String(16), default="auto", server_default="auto")
    primary_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("content_assets.id", name="fk_submodule_primary_asset", ondelete="SET NULL"), nullable=True)
    content_mode: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    content_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    content_object_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    order: Mapped[int] = mapped_column(Integer)
    quiz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quizzes.id"), unique=True)
    requires_quiz: Mapped[bool] = mapped_column(Boolean, default=True)
    is_folder: Mapped[bool] = mapped_column(Boolean, default=False)
    outline_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    source_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    __table_args__ = (UniqueConstraint("module_id", "order", name="uq_submodule_module_order"),)
