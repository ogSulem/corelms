"""create sdlp core

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-07

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


quiz_type_enum = sa.Enum("submodule", "final", name="quiztype")
question_type_enum = sa.Enum("single", "multi", "case", name="questiontype")
assignment_type_enum = sa.Enum("module", "skill", name="assignmenttype")
assignment_status_enum = sa.Enum("pending", "in_progress", "completed", "overdue", name="assignmentstatus")
learning_event_type_enum = sa.Enum(
    "submodule_opened",
    "asset_viewed",
    "quiz_started",
    "quiz_completed",
    name="learningeventtype",
)


def upgrade() -> None:
    op.create_table(
        "skill_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
    )
    op.create_index("ix_skill_categories_name", "skill_categories", ["name"], unique=True)

    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skill_categories.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("max_level", sa.Integer(), nullable=False, server_default="10"),
        sa.UniqueConstraint("category_id", "name", name="uq_skill_category_name"),
    )
    op.create_index("ix_skills_category_id", "skills", ["category_id"], unique=False)
    op.create_index("ix_skills_name", "skills", ["name"], unique=False)

    op.create_table(
        "user_skills",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True, nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id"), primary_key=True, nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.String(length=5000), nullable=True),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("category", sa.String(length=200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_modules_title", "modules", ["title"], unique=False)

    op.create_table(
        "module_skill_map",
        sa.Column("module_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("modules.id"), primary_key=True, nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id"), primary_key=True, nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0"),
        sa.UniqueConstraint("module_id", "skill_id", name="uq_module_skill"),
    )

    op.create_table(
        "quizzes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("type", quiz_type_enum, nullable=False),
        sa.Column("pass_threshold", sa.Integer(), nullable=False, server_default="70"),
        sa.Column("time_limit", sa.Integer(), nullable=True),
        sa.Column("attempts_limit", sa.Integer(), nullable=False, server_default="3"),
    )
    op.create_index("ix_quizzes_type", "quizzes", ["type"], unique=False)

    op.create_table(
        "questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("quiz_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quizzes.id"), nullable=False),
        sa.Column("type", question_type_enum, nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prompt", sa.String(), nullable=False, server_default=""),
        sa.Column("correct_answer", sa.String(), nullable=False, server_default=""),
        sa.Column("explanation", sa.String(), nullable=True),
        sa.Column("concept_tag", sa.String(length=200), nullable=True),
        sa.Column("variant_group", sa.String(length=200), nullable=True),
    )
    op.create_index("ix_questions_quiz_id", "questions", ["quiz_id"], unique=False)
    op.create_index("ix_questions_type", "questions", ["type"], unique=False)

    op.create_table(
        "submodules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("modules.id"), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content", sa.String(), nullable=False, server_default=""),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("quiz_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quizzes.id"), nullable=False),
        sa.UniqueConstraint("module_id", "order", name="uq_submodule_module_order"),
        sa.UniqueConstraint("quiz_id", name="uq_submodule_quiz"),
    )
    op.create_index("ix_submodules_module_id", "submodules", ["module_id"], unique=False)

    op.create_table(
        "assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", assignment_type_enum, nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", assignment_status_enum, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_assignments_assigned_by", "assignments", ["assigned_by"], unique=False)
    op.create_index("ix_assignments_assigned_to", "assignments", ["assigned_to"], unique=False)
    op.create_index("ix_assignments_type", "assignments", ["type"], unique=False)
    op.create_index("ix_assignments_target_id", "assignments", ["target_id"], unique=False)

    op.create_table(
        "knowledge_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=400), nullable=False),
        sa.Column("content", sa.String(), nullable=False, server_default=""),
        sa.Column("tags", sa.String(), nullable=True),
        sa.Column("linked_skills", sa.String(), nullable=True),
        sa.Column("linked_modules", sa.String(), nullable=True),
    )
    op.create_index("ix_knowledge_articles_title", "knowledge_articles", ["title"], unique=False)

    op.create_table(
        "quiz_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("quiz_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quizzes.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("time_spent_seconds", sa.Integer(), nullable=True),
    )
    op.create_index("ix_quiz_attempts_quiz_id", "quiz_attempts", ["quiz_id"], unique=False)
    op.create_index("ix_quiz_attempts_user_id", "quiz_attempts", ["user_id"], unique=False)

    op.create_table(
        "quiz_attempt_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_attempts.id"), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("answer", sa.String(), nullable=False, server_default=""),
        sa.Column("is_correct", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_quiz_attempt_answers_attempt_id", "quiz_attempt_answers", ["attempt_id"], unique=False)
    op.create_index("ix_quiz_attempt_answers_question_id", "quiz_attempt_answers", ["question_id"], unique=False)

    op.create_table(
        "learning_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", learning_event_type_enum, nullable=False),
        sa.Column("ref_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("meta", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_learning_events_user_id", "learning_events", ["user_id"], unique=False)
    op.create_index("ix_learning_events_type", "learning_events", ["type"], unique=False)
    op.create_index("ix_learning_events_ref_id", "learning_events", ["ref_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_learning_events_ref_id", table_name="learning_events")
    op.drop_index("ix_learning_events_type", table_name="learning_events")
    op.drop_index("ix_learning_events_user_id", table_name="learning_events")
    op.drop_table("learning_events")

    op.drop_index("ix_quiz_attempt_answers_question_id", table_name="quiz_attempt_answers")
    op.drop_index("ix_quiz_attempt_answers_attempt_id", table_name="quiz_attempt_answers")
    op.drop_table("quiz_attempt_answers")

    op.drop_index("ix_quiz_attempts_user_id", table_name="quiz_attempts")
    op.drop_index("ix_quiz_attempts_quiz_id", table_name="quiz_attempts")
    op.drop_table("quiz_attempts")

    op.drop_index("ix_knowledge_articles_title", table_name="knowledge_articles")
    op.drop_table("knowledge_articles")

    op.drop_index("ix_assignments_target_id", table_name="assignments")
    op.drop_index("ix_assignments_type", table_name="assignments")
    op.drop_index("ix_assignments_assigned_to", table_name="assignments")
    op.drop_index("ix_assignments_assigned_by", table_name="assignments")
    op.drop_table("assignments")

    op.drop_index("ix_submodules_module_id", table_name="submodules")
    op.drop_table("submodules")

    op.drop_index("ix_questions_type", table_name="questions")
    op.drop_index("ix_questions_quiz_id", table_name="questions")
    op.drop_table("questions")

    op.drop_index("ix_quizzes_type", table_name="quizzes")
    op.drop_table("quizzes")

    op.drop_table("module_skill_map")

    op.drop_index("ix_modules_title", table_name="modules")
    op.drop_table("modules")

    op.drop_table("user_skills")

    op.drop_index("ix_skills_name", table_name="skills")
    op.drop_index("ix_skills_category_id", table_name="skills")
    op.drop_table("skills")

    op.drop_index("ix_skill_categories_name", table_name="skill_categories")
    op.drop_table("skill_categories")

    op.execute("DROP TYPE IF EXISTS learningeventtype")
    op.execute("DROP TYPE IF EXISTS assignmentstatus")
    op.execute("DROP TYPE IF EXISTS assignmenttype")
    op.execute("DROP TYPE IF EXISTS questiontype")
    op.execute("DROP TYPE IF EXISTS quiztype")
