from __future__ import annotations

from pydantic import BaseModel


class ModulePublic(BaseModel):
    id: str
    title: str
    description: str | None
    difficulty: int
    category: str | None
    is_active: bool


class SubmodulePublic(BaseModel):
    id: str
    module_id: str
    title: str
    order: int
    quiz_id: str
    requires_quiz: bool
    is_folder: bool
    outline_path: str | None


class AssetPublic(BaseModel):
    """Файл в кабинете ученика.

    Ключа объекта в хранилище здесь нет: он внутренний, наружу не нужен, а в
    старых ответах уходил в браузер вместе со списком материалов.
    """

    asset_id: str
    original_filename: str
    mime_type: str | None
    size_bytes: int | None = None
    order: int
    version: int = 1


class SubmoduleAssetsResponse(BaseModel):
    submodule_id: str
    assets: list[AssetPublic]


class ModuleSkillPublic(BaseModel):
    skill: str
    category: str
    weight: float


class ModuleSkillsResponse(BaseModel):
    module_id: str
    skills: list[ModuleSkillPublic]
