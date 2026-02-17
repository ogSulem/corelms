from __future__ import annotations

from pydantic import BaseModel


class SubmoduleStatus(BaseModel):
    submodule_id: str
    quiz_id: str
    read: bool
    passed: bool
    best_score: int | None
    last_score: int | None = None
    last_passed: bool | None = None
    locked: bool = False
    locked_reason: str | None = None
    is_final: bool = False


class ModuleProgressResponse(BaseModel):
    module_id: str
    total: int
    passed: int
    final_submodule_id: str | None
    final_quiz_id: str | None
    final_passed: bool
    final_best_score: int | None = None
    completed: bool
    submodules: list[SubmoduleStatus]
