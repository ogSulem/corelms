from __future__ import annotations

import uuid
from typing import Annotated, Literal
from pydantic import BaseModel, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class RevisionRequest(BaseModel):
    revision: int = Field(ge=1)


class ModuleDraft(BaseModel):
    title: Title
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, max_length=200)


class ModuleEdit(RevisionRequest):
    visibility: Literal["public", "restricted", "hidden"] | None = None
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    title: Title | None = None
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    is_archived: bool | None = None


class LessonDraft(RevisionRequest):
    presentation_mode: Literal["auto", "material", "text"] = "auto"
    title: Title
    content: str = Field(default="", max_length=500_000)
    is_folder: bool = False
    outline_path: str | None = Field(default=None, max_length=1000)


class LessonEdit(RevisionRequest):
    presentation_mode: Literal["auto", "material", "text"] | None = None
    primary_asset_id: uuid.UUID | None = None
    content_mode: Literal["manual", "import"] | None = None
    title: Title | None = None
    content: str | None = Field(default=None, max_length=500_000)
    outline_path: str | None = Field(default=None, max_length=1000)
    requires_quiz: bool | None = None
    is_archived: bool | None = None


class ReorderRequest(RevisionRequest):
    ids: list[uuid.UUID] = Field(max_length=12000)
    submodule_id: uuid.UUID | None = None


class AssetEdit(RevisionRequest):
    filename: str | None = Field(default=None, max_length=400)
    # Путь папки внутри урока/каталога. Пустая строка — корень раздела.
    folder: str | None = Field(default=None, max_length=390)
    is_archived: bool | None = None
    submodule_id: uuid.UUID | None = None


class MoveAssets(RevisionRequest):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    submodule_id: uuid.UUID | None = None
    folder: str | None = Field(default=None, max_length=390)


class DeleteAssets(RevisionRequest):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class DeleteLesson(RevisionRequest):
    pass


class VersionRestore(RevisionRequest):
    version: int = Field(ge=1)


class UploadStart(RevisionRequest):
    """Начало частичной загрузки: имя, размер и место файла известны заранее."""
    filename: str = Field(min_length=1, max_length=400)
    size_bytes: int = Field(ge=1, le=20 * 1024 * 1024 * 1024)
    submodule_id: uuid.UUID | None = None
    replace_asset_id: uuid.UUID | None = None
    create_lesson: bool = False


class ArchiveAssets(RevisionRequest):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    is_archived: bool = True
