from __future__ import annotations

from pydantic import BaseModel, Field


class QuizQuestionPublic(BaseModel):
    id: str
    prompt: str
    type: str


class QuizStartResponse(BaseModel):
    quiz_id: str
    session_id: str
    started_at: int
    pass_threshold: int
    attempt_no: int
    attempts_limit: int | None = None
    time_limit: int | None
    questions: list[QuizQuestionPublic]


class QuizSubmitAnswer(BaseModel):
    question_id: str = Field(max_length=64)
    answer: str = Field(max_length=20000)


class QuizSubmitRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    answers: list[QuizSubmitAnswer] = Field(max_length=1000)


class QuizSubmitResponse(BaseModel):
    quiz_id: str
    score: int
    passed: bool
    correct: int
    total: int
    xp_awarded: int
    replayed: bool = False
