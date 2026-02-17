from __future__ import annotations

from pydantic import BaseModel


class QuizQuestionPublic(BaseModel):
    id: str
    prompt: str
    type: str


class QuizStartResponse(BaseModel):
    quiz_id: str
    attempt_no: int
    time_limit: int | None
    questions: list[QuizQuestionPublic]


class QuizSubmitAnswer(BaseModel):
    question_id: str
    answer: str


class QuizSubmitRequest(BaseModel):
    answers: list[QuizSubmitAnswer]


class QuizSubmitResponse(BaseModel):
    quiz_id: str
    score: int
    passed: bool
    correct: int
    total: int
    xp_awarded: int
