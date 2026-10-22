from __future__ import annotations

import uuid
import re
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from app.schemas.content import RevisionRequest


class QuestionDraft(BaseModel):
    id: uuid.UUID | None = None
    type: Literal["single", "multi"] = "single"
    stem: str = Field(min_length=1, max_length=12000)
    options: list[str] = Field(min_length=2, max_length=5)
    correct: list[int] = Field(min_length=1, max_length=5)
    explanation: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def valid_question(self):
        self.stem = self.stem.strip()
        self.options = [str(x).strip() for x in self.options]
        if not self.stem or any(not x or len(x) > 3000 for x in self.options):
            raise ValueError("Заполните вопрос и все варианты ответа (до 3000 символов)")
        if len({" ".join(x.casefold().split()) for x in self.options}) != len(self.options):
            raise ValueError("Варианты ответа не должны совпадать")
        if len(set(self.correct)) != len(self.correct) or any(i < 0 or i >= len(self.options) for i in self.correct):
            raise ValueError("Правильный ответ должен ссылаться на существующий вариант")
        # The legacy storage/public format separates options by A), B), … lines.
        # Reject ambiguous embedded labels rather than silently re-parsing them
        # as a different bank after a successful structured save.
        labelled = re.compile(r"^[A-EАБВГД][).:]", re.IGNORECASE)
        if any(labelled.match(line.strip()) for line in self.stem.splitlines()) or any(
            labelled.match(line.strip()) for option in self.options for line in option.splitlines()[1:]
        ):
            raise ValueError("Уберите строки с метками A), B) и т. п. из формулировки и внутренних списков: варианты задаются отдельными полями")
        if self.type == "single" and len(self.correct) != 1:
            raise ValueError("У вопроса с одним ответом отметьте ровно один правильный вариант")
        return self


class QuizSettings(BaseModel):
    enabled: bool = False
    pass_threshold: int = Field(default=70, ge=1, le=100)
    time_limit: int | None = Field(default=None, ge=60, le=14400)
    attempts_limit: int = Field(default=3, ge=0, le=100)


class QuizSave(QuizSettings, RevisionRequest):
    questions: list[QuestionDraft] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid_bank(self):
        if self.enabled and not self.questions:
            raise ValueError("Для обязательного теста нужен хотя бы один вопрос")
        ids = [q.id for q in self.questions if q.id]
        if len(set(ids)) != len(ids):
            raise ValueError("Вопрос не должен повторяться")
        return self


class FinalQuizSave(QuizSettings, RevisionRequest):
    pass


class GenerateDraft(RevisionRequest):
    count: int = Field(default=5, ge=1, le=10)
    source_text: str | None = Field(default=None, max_length=60000)
