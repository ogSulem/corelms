from __future__ import annotations

from pydantic import BaseModel


class UserPublic(BaseModel):
    id: str
    name: str
    role: str
    position: str | None


class UserListResponse(BaseModel):
    items: list[UserPublic]


class EvidenceAttempt(BaseModel):
    quiz_id: str
    attempt_no: int
    score: int | None
    passed: bool
    started_at: str
    finished_at: str | None


class EvidenceEvent(BaseModel):
    type: str
    ref_id: str | None
    created_at: str
    meta: str | None


class UserEvidenceResponse(BaseModel):
    user_id: str
    attempts: list[EvidenceAttempt]
    events: list[EvidenceEvent]
