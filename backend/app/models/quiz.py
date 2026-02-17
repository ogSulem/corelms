import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QuizType(str, enum.Enum):
    submodule = "submodule"
    final = "final"


class QuestionType(str, enum.Enum):
    single = "single"
    multi = "multi"
    case = "case"


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[QuizType] = mapped_column(Enum(QuizType), index=True)
    pass_threshold: Mapped[int] = mapped_column(Integer, default=70)
    time_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts_limit: Mapped[int] = mapped_column(Integer, default=3)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quiz_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quizzes.id"), index=True)

    type: Mapped[QuestionType] = mapped_column(Enum(QuestionType), index=True)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)

    prompt: Mapped[str] = mapped_column(String, default="")
    correct_answer: Mapped[str] = mapped_column(String, default="")
    explanation: Mapped[str | None] = mapped_column(String, nullable=True)

    concept_tag: Mapped[str | None] = mapped_column(String(200), nullable=True)
    variant_group: Mapped[str | None] = mapped_column(String(200), nullable=True)
