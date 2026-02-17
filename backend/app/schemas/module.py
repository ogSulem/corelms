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


class AssetPublic(BaseModel):
    asset_id: str
    object_key: str
    original_filename: str
    mime_type: str | None
    order: int


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
