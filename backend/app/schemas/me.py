from __future__ import annotations

from pydantic import BaseModel


class AssignmentItem(BaseModel):
    id: str
    type: str
    target_id: str
    status: str
    priority: int
    deadline: str | None


class MyAssignmentsResponse(BaseModel):
    items: list[AssignmentItem]


class MyProfileResponse(BaseModel):
    id: str
    name: str
    role: str
    position: str | None
    xp: int
    level: int
    streak: int
    last_activity_at: str | None = None


class RecentAttempt(BaseModel):
    quiz_id: str
    attempt_no: int
    score: int | None
    passed: bool
    started_at: str
    finished_at: str | None
    module_id: str | None = None
    module_title: str | None = None
    submodule_id: str | None = None
    submodule_title: str | None = None
    href: str | None = None


class RecentEvent(BaseModel):
    type: str
    ref_id: str | None
    created_at: str
    meta: str | None
    title: str | None = None
    subtitle: str | None = None
    module_id: str | None = None
    module_title: str | None = None
    submodule_id: str | None = None
    submodule_title: str | None = None
    asset_id: str | None = None
    asset_name: str | None = None
    href: str | None = None


class MyRecentActivityResponse(BaseModel):
    attempts: list[RecentAttempt]
    events: list[RecentEvent]


class ActivityFeedItem(BaseModel):
    kind: str
    created_at: str
    title: str
    subtitle: str | None = None
    status: str | None = None
    score: int | None = None
    passed: bool | None = None
    count: int | None = None
    duration_seconds: int | None = None
    module_id: str | None = None
    module_title: str | None = None
    submodule_id: str | None = None
    submodule_title: str | None = None
    href: str | None = None


class MyActivityFeedResponse(BaseModel):
    items: list[ActivityFeedItem]


class HistoryItem(BaseModel):
    id: str
    created_at: str
    kind: str
    title: str
    subtitle: str | None = None
    status: str | None = None
    score: int | None = None
    passed: bool | None = None
    duration_seconds: int | None = None
    href: str | None = None
    # raw
    event_type: str | None = None
    ref_id: str | None = None
    meta: str | None = None
    ip: str | None = None
    request_id: str | None = None
    # context
    module_id: str | None = None
    module_title: str | None = None
    submodule_id: str | None = None
    submodule_title: str | None = None
    asset_id: str | None = None
    asset_name: str | None = None


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
