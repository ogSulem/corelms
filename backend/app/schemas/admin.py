from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.models.user import UserRole


class ModuleCreateRequest(BaseModel):
    title: str
    description: str | None = None
    difficulty: int = 1
    category: str | None = None
    is_active: bool = True


class ModuleCreateResponse(BaseModel):
    id: str


class QuizCreateRequest(BaseModel):
    type: str  # submodule/final
    pass_threshold: int = 70
    time_limit: int | None = None
    attempts_limit: int = 3


class QuizCreateResponse(BaseModel):
    id: str


class QuestionCreateRequest(BaseModel):
    quiz_id: str
    type: str  # single/multi/case
    difficulty: int = 1
    prompt: str
    correct_answer: str
    explanation: str | None = None
    concept_tag: str | None = None
    variant_group: str | None = None


class QuestionCreateResponse(BaseModel):
    id: str


class QuestionPublic(BaseModel):
    id: str
    quiz_id: str
    type: str
    difficulty: int
    prompt: str
    correct_answer: str
    explanation: str | None = None
    concept_tag: str | None = None
    variant_group: str | None = None


class QuestionsListResponse(BaseModel):
    items: list[QuestionPublic]


class QuestionUpdateRequest(BaseModel):
    type: str | None = None
    difficulty: int | None = None
    prompt: str | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    concept_tag: str | None = None
    variant_group: str | None = None


class QuestionUpdateResponse(BaseModel):
    ok: bool = True
    item: QuestionPublic


class SubmoduleCreateRequest(BaseModel):
    module_id: str
    title: str
    order: int
    quiz_id: str


class SubmoduleCreateResponse(BaseModel):
    id: str


class LinkAssetToSubmoduleRequest(BaseModel):
    submodule_id: str
    asset_id: str
    order: int = 1


class LinkAssetToSubmoduleResponse(BaseModel):
    ok: bool = True


class AssignmentCreateRequest(BaseModel):
    assigned_to: str
    type: str  # module/skill
    target_id: str
    priority: int = 1
    deadline: str | None = None


class AssignmentCreateResponse(BaseModel):
    id: str


class UserCreateRequest(BaseModel):
    name: str
    position: str | None = None
    role: Literal["employee", "admin"] = "employee"
    password: str | None = None
    must_change_password: bool = True


class UserCreateResponse(BaseModel):
    id: str
    temp_password: str | None = None


class UserResetPasswordRequest(BaseModel):
    password: str | None = None
    must_change_password: bool = True


class UserResetPasswordResponse(BaseModel):
    ok: bool = True
    temp_password: str | None = None
