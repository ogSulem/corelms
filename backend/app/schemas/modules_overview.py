from __future__ import annotations

from pydantic import BaseModel


class ModuleProgressPreview(BaseModel):
    read_count: int
    total_lessons: int
    passed_count: int
    final_passed: bool
    completed: bool


class ModuleOverviewItem(BaseModel):
    id: str
    title: str
    description: str | None
    difficulty: int
    category: str | None
    is_active: bool
    progress: ModuleProgressPreview


class ModulesOverviewResponse(BaseModel):
    items: list[ModuleOverviewItem]
