from __future__ import annotations

from pydantic import BaseModel


class SkillsCoverageRow(BaseModel):
    module_id: str
    module_title: str
    module_category: str | None
    mapped_skills: int


class SkillsCoverageResponse(BaseModel):
    total_modules: int
    mapped_modules: int
    unmapped_modules: int
    rows: list[SkillsCoverageRow]


class SkillSeedResponse(BaseModel):
    ok: bool
    categories_created: int
    skills_created: int


class AutoMapSkillsResponse(BaseModel):
    ok: bool
    mappings_created: int
