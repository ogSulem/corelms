from __future__ import annotations

from pydantic import BaseModel


class ModuleUserProgressRow(BaseModel):
    user_id: str
    name: str
    role: str
    read_count: int
    passed_count: int
    total_lessons: int
    final_passed: bool
    completed: bool
    last_activity: str | None


class ModuleAnalyticsResponse(BaseModel):
    module_id: str
    module_title: str
    rows: list[ModuleUserProgressRow]
