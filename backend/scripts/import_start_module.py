from __future__ import annotations

import argparse
import mimetypes
import pathlib
import re
import sys
import os
import uuid

# Force /app into path for Docker compatibility
sys.path.append("/app")
# Also add current directory as fallback
sys.path.append(os.getcwd())

from passlib.context import CryptContext
from sqlalchemy import delete, func, select, update

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.asset import ContentAsset
from app.models.module import Module, Submodule
from app.models.quiz import Question, QuestionType, Quiz, QuizType
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.user import User, UserRole
from app.services.storage import ensure_bucket_exists, get_s3_client

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-zа-я0-9._-]+", "-", s, flags=re.IGNORECASE)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "file"


_STEP_RE = re.compile(r"^\s*(\d+)\s*[.)\-_ ]\s*(.+?)\s*$")


def _upsert_step_quiz_questions(*, db, quiz_id: uuid.UUID, step: int, sub_title: str) -> None:
    """Idempotently ensure a real quiz exists for a learning step.

    We keep it deterministic via concept_tag, so re-import won't duplicate.
    If the quiz contains only the old placeholder 'start_ack' question, we replace it.
    """

    existing = list(
        db.scalars(
            select(Question).where(Question.quiz_id == quiz_id).order_by(Question.id)
        )
    )

    if existing and any((q.concept_tag or "").startswith(f"start_s{step}_") for q in existing):
        return

    if len(existing) == 1 and (existing[0].concept_tag or "") == "start_ack":
        db.execute(delete(Question).where(Question.id == existing[0].id))

    # Questions are stored without explicit variants in schema; we include options in prompt.
    # correct_answer is the expected string (case-insensitive). For multi: comma-separated.
    q: list[Question] = []

    if step == 1:
        q = [
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р вЂ™РЎвЂ№Р В±Р С•РЎР‚ Р С›Р СџР В¤: Р С”Р В°Р С”Р С•Р в„– Р Р†Р В°РЎР‚Р С‘Р В°Р Р…РЎвЂљ Р С•РЎР‚Р С–Р В°Р Р…Р С‘Р В·Р В°РЎвЂ Р С‘Р С•Р Р…Р Р…Р С•РІР‚вЂР С—РЎР‚Р В°Р Р†Р С•Р Р†Р С•Р в„– РЎвЂћР С•РЎР‚Р СРЎвЂ№ РЎС“Р С—Р С•Р СР С‘Р Р…Р В°Р ВµРЎвЂљРЎРѓРЎРЏ Р С”Р В°Р С” Р С—РЎР‚Р С‘Р СР ВµРЎР‚?\n"
                    "A) Р С’Р С›\nB) Р С›Р С›Р С›\nC) Р СџР С’Р С›\nD) Р СњР С™Р С›"
                ),
                correct_answer="B",
                explanation=None,
                concept_tag="start_s1_q1",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р СњР В° РЎвЂЎРЎвЂљР С• Р Р†Р В°Р В¶Р Р…Р С• Р С•Р В±РЎР‚Р В°РЎвЂљР С‘РЎвЂљРЎРЉ Р Р†Р Р…Р С‘Р СР В°Р Р…Р С‘Р Вµ Р С—РЎР‚Р С‘ РЎР‚Р ВµР С–Р С‘РЎРѓРЎвЂљРЎР‚Р В°РЎвЂ Р С‘Р С‘ РЎР‹РЎР‚Р В»Р С‘РЎвЂ Р В°?\n"
                    "A) Р С›Р вЂњР В Р Сњ\nB) Р С›Р С™Р вЂ™Р В­Р вЂќ\nC) Р ВР СњР Сњ\nD) Р С™Р СџР Сџ"
                ),
                correct_answer="B",
                explanation=None,
                concept_tag="start_s1_q2",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р вЂ”Р В°РЎвЂЎР ВµР С Р Р…РЎС“Р В¶Р ВµР Р… Р В°Р Р…Р В°Р В»Р С‘Р В· Р С”Р С•Р Р…Р С”РЎС“РЎР‚Р ВµР Р…РЎвЂљР С•Р Р† (Р С”Р В»РЎР‹РЎвЂЎР ВµР Р†Р В°РЎРЏ Р С—РЎР‚Р С‘РЎвЂЎР С‘Р Р…Р В° Р С‘Р В· Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»Р В°)?\n"
                    "A) Р В§РЎвЂљР С•Р В±РЎвЂ№ Р Р†Р ВµРЎРѓРЎвЂљР С‘ Р Т‘Р С‘Р В°Р В»Р С•Р С– Р С—РЎР‚Р ВµР Т‘Р СР ВµРЎвЂљР Р…Р С•\nB) Р В§РЎвЂљР С•Р В±РЎвЂ№ Р С—Р С•Р Р†РЎвЂ№РЎРѓР С‘РЎвЂљРЎРЉ Р Р…Р В°Р В»Р С•Р С–Р С‘\nC) Р В§РЎвЂљР С•Р В±РЎвЂ№ Р Р…Р Вµ Р С•Р В±РЎвЂ°Р В°РЎвЂљРЎРЉРЎРѓРЎРЏ РЎРѓ Р С”Р В»Р С‘Р ВµР Р…РЎвЂљР В°Р СР С‘\nD) Р В§РЎвЂљР С•Р В±РЎвЂ№ Р С•РЎвЂљР СР ВµР Р…Р С‘РЎвЂљРЎРЉ Р С—РЎР‚Р С•Р Т‘Р В°Р В¶Р С‘"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s1_q3",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р В§РЎвЂљР С• Р Р†Р В°Р В¶Р Р…Р С• РЎС“РЎвЂЎР ВµРЎРѓРЎвЂљРЎРЉ Р С—РЎР‚Р С‘ Р В°Р Р…Р В°Р В»Р С‘Р В·Р Вµ Р С—Р С•РЎРѓРЎвЂљР В°Р Р†РЎвЂ°Р С‘Р С”Р С•Р Р† (1 Р С—РЎС“Р Р…Р С”РЎвЂљ Р С‘Р В· РЎвЂљР ВµР С”РЎРѓРЎвЂљР В°)?\n"
                    "A) Р вЂ™Р С•Р В·Р СР С•Р В¶Р Р…Р С•РЎРѓРЎвЂљРЎРЉ Р Т‘Р С‘РЎРѓРЎвЂљР В°Р Р…РЎвЂ Р С‘Р С•Р Р…Р Р…Р С•Р в„– Р С•РЎвЂљР С–РЎР‚РЎС“Р В·Р С”Р С‘\nB) Р В¦Р Р†Р ВµРЎвЂљ Р В»Р С•Р С–Р С•РЎвЂљР С‘Р С—Р В°\nC) Р С™Р С•Р В»Р С‘РЎвЂЎР ВµРЎРѓРЎвЂљР Р†Р С• Р С—Р С•Р Т‘Р С—Р С‘РЎРѓРЎвЂЎР С‘Р С”Р С•Р Р†\nD) Р СњР В°Р В·Р Р†Р В°Р Р…Р С‘Р Вµ Р Т‘Р С•Р СР ВµР Р…Р В°"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s1_q4",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.multi,
                difficulty=2,
                prompt=(
                    "Р вЂ™РЎвЂ№Р В±Р ВµРЎР‚Р С‘ Р С—РЎС“Р Р…Р С”РЎвЂљРЎвЂ№, Р С”Р С•РЎвЂљР С•РЎР‚РЎвЂ№Р Вµ Р Р† Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»Р Вµ Р С—Р ВµРЎР‚Р ВµРЎвЂЎР С‘РЎРѓР В»Р ВµР Р…РЎвЂ№ Р С”Р В°Р С” РЎРЊРЎвЂљР В°Р С—РЎвЂ№/Р С‘Р Р…РЎРѓРЎвЂљРЎР‚РЎС“Р СР ВµР Р…РЎвЂљРЎвЂ№. Р С›РЎвЂљР Р†Р ВµРЎвЂљ Р В±РЎС“Р С”Р Р†Р В°Р СР С‘ (Р С—РЎР‚Р С‘Р СР ВµРЎР‚: ABD).\n"
                    "A) Р С’Р Р…Р В°Р В»Р С‘Р В· Р С”Р С•Р Р…Р С”РЎС“РЎР‚Р ВµР Р…РЎвЂљР С•Р Р†\nB) Р вЂ™Р В»Р С•Р В¶Р ВµР Р…Р С‘Р Вµ Р Р† РЎР‚Р ВµР С”Р В»Р В°Р СРЎС“\nC) Р СњР В°Р В±Р С•РЎР‚ SMMРІР‚вЂР С”Р С•Р СР В°Р Р…Р Т‘РЎвЂ№\nD) Р С’Р С”Р С”РЎР‚Р ВµР Т‘Р С‘РЎвЂљР В°РЎвЂ Р С‘РЎРЏ/Р С”РЎР‚Р ВµР Т‘Р С‘РЎвЂљ/Р Т‘Р С•Р С—. Р С—РЎР‚Р С•Р Т‘Р В°Р В¶Р С‘"
                ),
                correct_answer="A,B,D",
                explanation=None,
                concept_tag="start_s1_q5",
                variant_group=None,
            ),
        ]
    elif step == 2:
        q = [
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р С™РЎвЂљР С• Р С”РЎС“РЎР‚Р С‘РЎР‚РЎС“Р ВµРЎвЂљ Р С—Р В°РЎР‚РЎвЂљР Р…Р ВµРЎР‚Р С•Р Р† Р С‘ Р С”Р С•Р Р…РЎвЂљРЎР‚Р С•Р В»Р С‘РЎР‚РЎС“Р ВµРЎвЂљ РЎР‚Р ВµР С”Р В»Р В°Р СРЎС“ Р С‘ РЎРѓР С‘РЎРѓРЎвЂљР ВµР СР Р…РЎвЂ№Р Вµ Р С—РЎР‚Р С•РЎвЂ Р ВµРЎРѓРЎРѓРЎвЂ№?\n"
                    "A) Р В Р ВµР С–Р С‘Р С•Р Р…Р В°Р В»РЎРЉР Р…РЎвЂ№Р в„– Р Т‘Р С‘РЎР‚Р ВµР С”РЎвЂљР С•РЎР‚\nB) Р В Р ВµР С”РЎР‚РЎС“РЎвЂљР ВµРЎР‚\nC) Р вЂРЎС“РЎвЂ¦Р С–Р В°Р В»РЎвЂљР ВµРЎР‚\nD) Р С™Р С•Р Р…РЎвЂљР ВµРЎРѓРЎвЂљР С•Р В»Р С•Р С–"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s2_q1",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р С™Р В°Р С”Р В°РЎРЏ РЎР‚Р С•Р В»РЎРЉ Р С•Р В±РЎС“РЎвЂЎР В°Р ВµРЎвЂљ Р СР ВµР Р…Р ВµР Т‘Р В¶Р ВµРЎР‚Р С•Р Р† Р С‘ Р С”Р С•Р Р…РЎвЂљРЎР‚Р С•Р В»Р С‘РЎР‚РЎС“Р ВµРЎвЂљ Р Р†РЎРѓРЎвЂљРЎР‚Р ВµРЎвЂЎР С‘?\n"
                    "A) Р В РЎС“Р С”Р С•Р Р†Р С•Р Т‘Р С‘РЎвЂљР ВµР В»РЎРЉ Р С•РЎвЂљР Т‘Р ВµР В»Р В° Р С—РЎР‚Р С•Р Т‘Р В°Р В¶\nB) Р СџРЎР‚Р С•Р ВµР С”РЎвЂљР С‘РЎР‚Р С•Р Р†РЎвЂ°Р С‘Р С”\nC) Р В­Р С”РЎРѓР С—Р ВµРЎР‚РЎвЂљ Р С—Р С• РЎРѓРЎвЂљРЎР‚Р С•Р в„–Р С”Р Вµ\nD) Р С’Р Р†Р С‘РЎвЂљР С•Р В»Р С•Р С–"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s2_q2",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р С™РЎвЂљР С• Р В·Р В°Р С—РЎС“РЎРѓР С”Р В°Р ВµРЎвЂљ РЎР‚Р ВµР С”Р В»Р В°Р СРЎС“ Р С’Р Р†Р С‘РЎвЂљР С• Р С‘ Р В°Р Р…Р В°Р В»Р С‘Р В·Р С‘РЎР‚РЎС“Р ВµРЎвЂљ РЎРѓРЎвЂљР С•Р С‘Р СР С•РЎРѓРЎвЂљРЎРЉ Р В»Р С‘Р Т‘Р В°?\n"
                    "A) Р С’Р Р†Р С‘РЎвЂљР С•Р В»Р С•Р С–\nB) Р В Р ВµР С”РЎР‚РЎС“РЎвЂљР ВµРЎР‚\nC) Р В Р ВµР С–Р С‘Р С•Р Р…Р В°Р В»РЎРЉР Р…РЎвЂ№Р в„– Р Т‘Р С‘РЎР‚Р ВµР С”РЎвЂљР С•РЎР‚\nD) Р С™Р С•Р Р…РЎвЂљР ВµРЎРѓРЎвЂљР С•Р В»Р С•Р С–"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s2_q3",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р С™РЎвЂљР С• Р С—РЎР‚Р С•Р Р†Р ВµРЎР‚РЎРЏР ВµРЎвЂљ Р В·Р В°РЎРЏР Р†Р С”Р С‘ Р С‘ РЎР‚Р В°РЎРѓР С—РЎР‚Р ВµР Т‘Р ВµР В»РЎРЏР ВµРЎвЂљ Р В»Р С‘Р Т‘РЎвЂ№ Р СР ВµР В¶Р Т‘РЎС“ Р СР ВµР Р…Р ВµР Т‘Р В¶Р ВµРЎР‚Р В°Р СР С‘?\n"
                    "A) Р С™Р В»Р В°РЎРѓРЎРѓР С‘РЎвЂћР С‘Р С”Р В°РЎвЂљР С•РЎР‚ Р В»Р С‘Р Т‘Р С•Р Р†\nB) Р СџРЎР‚Р С•Р ВµР С”РЎвЂљР С‘РЎР‚Р С•Р Р†РЎвЂ°Р С‘Р С”\nC) Р В­Р С”РЎРѓР С—Р ВµРЎР‚РЎвЂљ Р С—Р С• РЎРѓРЎвЂљРЎР‚Р С•Р в„–Р С”Р Вµ\nD) Р С’Р Р†Р С‘РЎвЂљР С•Р В»Р С•Р С–"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s2_q4",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.multi,
                difficulty=2,
                prompt=(
                    "Р вЂ™РЎвЂ№Р В±Р ВµРЎР‚Р С‘ Р Т‘Р С•Р В»Р В¶Р Р…Р С•РЎРѓРЎвЂљР С‘, Р С•РЎвЂљР Р…Р С•РЎРѓРЎРЏРЎвЂ°Р С‘Р ВµРЎРѓРЎРЏ Р С” РЎвЂљР ВµРЎвЂ¦Р Р…Р С‘РЎвЂЎР ВµРЎРѓР С”Р С•Р СРЎС“ Р С•РЎвЂљР Т‘Р ВµР В»РЎС“ (Р С•РЎвЂљР Р†Р ВµРЎвЂљ Р В±РЎС“Р С”Р Р†Р В°Р СР С‘, Р С—РЎР‚Р С‘Р СР ВµРЎР‚: AB).\n"
                    "A) Р В­Р С”РЎРѓР С—Р ВµРЎР‚РЎвЂљ Р С—Р С• РЎРѓРЎвЂљРЎР‚Р С•Р в„–Р С”Р Вµ\nB) Р СџРЎР‚Р С•Р ВµР С”РЎвЂљР С‘РЎР‚Р С•Р Р†РЎвЂ°Р С‘Р С”\nC) Р В Р ВµР С”РЎР‚РЎС“РЎвЂљР ВµРЎР‚\nD) Р С™Р С•Р Р…РЎвЂљР ВµРЎРѓРЎвЂљР С•Р В»Р С•Р С–"
                ),
                correct_answer="A,B",
                explanation=None,
                concept_tag="start_s2_q5",
                variant_group=None,
            ),
        ]
    elif step == 3:
        q = [
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р вЂ”Р В°РЎвЂЎР ВµР С Р Р…РЎС“Р В¶Р Р…РЎвЂ№ TelegramРІР‚вЂР С–РЎР‚РЎС“Р С—Р С—РЎвЂ№ Р С—Р В°РЎР‚РЎвЂљР Р…РЎвЂРЎР‚Р В°Р С (Р С”Р В»РЎР‹РЎвЂЎР ВµР Р†Р В°РЎРЏ РЎвЂ Р ВµР В»РЎРЉ Р С‘Р В· РЎвЂљР ВµР С”РЎРѓРЎвЂљР В°)?\n"
                    "A) Р вЂРЎвЂ№РЎРѓРЎвЂљРЎР‚Р С• Р Р…Р В°РЎвЂ¦Р С•Р Т‘Р С‘РЎвЂљРЎРЉ РЎвЂћР В°Р в„–Р В»РЎвЂ№\nB) Р вЂ”Р В°Р С—РЎР‚Р ВµРЎвЂљР С‘РЎвЂљРЎРЉ Р С”Р С•Р СР СРЎС“Р Р…Р С‘Р С”Р В°РЎвЂ Р С‘Р С‘\nC) Р СџР С•Р Р†РЎвЂ№РЎРѓР С‘РЎвЂљРЎРЉ РЎв‚¬РЎвЂљРЎР‚Р В°РЎвЂћРЎвЂ№\nD) Р ВРЎРѓР С”Р В»РЎР‹РЎвЂЎР С‘РЎвЂљРЎРЉ Р С—Р С•Р Т‘Р Т‘Р ВµРЎР‚Р В¶Р С”РЎС“"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s3_q1",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р С™Р В°Р С”Р В°РЎРЏ Р С–РЎР‚РЎС“Р С—Р С—Р В° Р Р…РЎС“Р В¶Р Р…Р В° Р Т‘Р В»РЎРЏ Р Т‘Р С•Р С–Р С•Р Р†Р С•РЎР‚Р С•Р Р† Р С‘ Р Т‘Р С•Р С—РЎРѓР С•Р С–Р В»Р В°РЎв‚¬Р ВµР Р…Р С‘Р в„–?\n"
                    "A) Р СџР С•Р СР С•РЎвЂ°Р Р…Р С‘Р С” Р Т‘Р С•Р С–Р С•Р Р†Р С•РЎР‚Р В° Р С‘ Р Т‘Р С•Р С—РЎРѓР С•Р С–Р В»Р В°РЎв‚¬Р ВµР Р…Р С‘РЎРЏ\nB) Р В¤Р С•РЎвЂљР С•РІР‚вЂР В±Р С‘Р В±Р В»Р С‘Р С•РЎвЂљР ВµР С”Р В°\nC) Р СњР С•Р Р†Р С•РЎРѓРЎвЂљР С‘\nD) Р С›РЎвЂљР Т‘Р ВµР В» Р С—РЎР‚Р С•Р Т‘Р В°Р В¶ Р С—Р В°РЎР‚РЎвЂљР Р…РЎвЂРЎР‚Р В°"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s3_q2",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р вЂњР Т‘Р Вµ Р Р…Р В°РЎвЂ¦Р С•Р Т‘Р С‘РЎвЂљРЎРѓРЎРЏ Р С”Р В°Р В»РЎРЉР С”РЎС“Р В»РЎРЏРЎвЂљР С•РЎР‚ РЎРѓР ВµР В±Р ВµРЎРѓРЎвЂљР С•Р С‘Р СР С•РЎРѓРЎвЂљР С‘ Р Т‘Р В»РЎРЏ Р В±РЎвЂ№РЎРѓРЎвЂљРЎР‚Р С•Р С–Р С• РЎР‚Р В°РЎРѓРЎвЂЎРЎвЂРЎвЂљР В°?\n"
                    "A) Р С™Р В°Р В»РЎРЉР С”РЎС“Р В»РЎРЏРЎвЂљР С•РЎР‚ РЎвЂ Р ВµР Р…\nB) Р СњР С•Р Р†Р С•РЎРѓРЎвЂљР С‘\nC) Р В¤Р С•РЎвЂљР С•РІР‚вЂР В±Р С‘Р В±Р В»Р С‘Р С•РЎвЂљР ВµР С”Р В°\nD) Р С›Р В±РЎвЂ°Р В°РЎРЏ Р С–РЎР‚РЎС“Р С—Р С—Р В° Р С—Р В°РЎР‚РЎвЂљР Р…РЎвЂРЎР‚Р В° РЎРѓ Р В Р вЂќ"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s3_q3",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.multi,
                difficulty=2,
                prompt=(
                    "Р вЂ™РЎвЂ№Р В±Р ВµРЎР‚Р С‘ Р С–РЎР‚РЎС“Р С—Р С—РЎвЂ№, Р С”Р С•РЎвЂљР С•РЎР‚РЎвЂ№Р Вµ Р С•РЎвЂљР Р…Р С•РЎРѓРЎРЏРЎвЂљРЎРѓРЎРЏ Р С” Р С‘Р Р…РЎРѓРЎвЂљРЎР‚РЎС“Р СР ВµР Р…РЎвЂљР В°Р С/Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»Р В°Р С (Р С•РЎвЂљР Р†Р ВµРЎвЂљ Р В±РЎС“Р С”Р Р†Р В°Р СР С‘, Р С—РЎР‚Р С‘Р СР ВµРЎР‚: AC).\n"
                    "A) Р В¤Р С•РЎвЂљР С•РІР‚вЂР В±Р С‘Р В±Р В»Р С‘Р С•РЎвЂљР ВµР С”Р В°\nB) Р С›РЎвЂљР Т‘Р ВµР В» Р С—РЎР‚Р С•Р Т‘Р В°Р В¶ Р С—Р В°РЎР‚РЎвЂљР Р…РЎвЂРЎР‚Р В°\nC) Р СџР С•Р СР С•РЎвЂ°Р Р…Р С‘Р С” РЎРѓРЎвЂљРЎР‚Р С•Р С‘РЎвЂљР ВµР В»РЎРЉРЎРѓРЎвЂљР Р†Р В° Р В±Р В°Р Р…РЎРЉ\nD) Р С›Р В±РЎвЂ°Р В°РЎРЏ Р С–РЎР‚РЎС“Р С—Р С—Р В° Р С—Р В°РЎР‚РЎвЂљР Р…РЎвЂРЎР‚Р В° РЎРѓ Р В Р вЂќ"
                ),
                correct_answer="A,C",
                explanation=None,
                concept_tag="start_s3_q4",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р В§РЎвЂљР С• Р Т‘Р ВµР В»Р В°РЎвЂљРЎРЉ, Р ВµРЎРѓР В»Р С‘ РЎвЂћР В°Р в„–Р В» Р Р† TelegramРІР‚вЂР С–РЎР‚РЎС“Р С—Р С—Р Вµ Р Р…Р Вµ Р Р…Р В°РЎв‚¬Р В»Р С‘?\n"
                    "A) Р СџР С‘РЎРѓР В°РЎвЂљРЎРЉ Р В Р вЂќ\nB) Р ВР С–Р Р…Р С•РЎР‚Р С‘РЎР‚Р С•Р Р†Р В°РЎвЂљРЎРЉ\nC) Р Р€Р Т‘Р В°Р В»Р С‘РЎвЂљРЎРЉ РЎвЂЎР В°РЎвЂљ\nD) Р вЂ“Р Т‘Р В°РЎвЂљРЎРЉ Р Р…Р ВµР Т‘Р ВµР В»РЎР‹"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s3_q5",
                variant_group=None,
            ),
        ]
    elif step == 4:
        q = [
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р вЂ”Р В° РЎРѓР С”Р С•Р В»РЎРЉР С”Р С• Р Т‘Р Р…Р ВµР в„– Р Т‘Р С• Р Р†РЎРѓРЎвЂљРЎР‚Р ВµРЎвЂЎР С‘ Р С•Р В±РЎвЂ№РЎвЂЎР Р…Р С• Р С—РЎР‚Р С‘РЎвЂ¦Р С•Р Т‘Р С‘РЎвЂљ РЎРѓРЎРѓРЎвЂ№Р В»Р С”Р В° Р Р…Р В° Р С—Р С•Р Т‘Р С”Р В»РЎР‹РЎвЂЎР ВµР Р…Р С‘Р Вµ Р Р…Р В° Р С—Р С•РЎвЂЎРЎвЂљРЎС“?\n"
                    "A) Р вЂ”Р В° Р Т‘Р ВµР Р…РЎРЉ\nB) Р вЂ”Р В° Р Р…Р ВµР Т‘Р ВµР В»РЎР‹\nC) Р вЂ”Р В° Р СР ВµРЎРѓРЎРЏРЎвЂ \nD) Р вЂ™ Р Т‘Р ВµР Р…РЎРЉ Р Р†РЎРѓРЎвЂљРЎР‚Р ВµРЎвЂЎР С‘"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s4_q1",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р вЂ”Р В° РЎРѓР С”Р С•Р В»РЎРЉР С”Р С• Р СР С‘Р Р…РЎС“РЎвЂљ Р Т‘Р С• Р Р…Р В°РЎвЂЎР В°Р В»Р В° РЎРѓРЎРѓРЎвЂ№Р В»Р С”Р В° Р Т‘РЎС“Р В±Р В»Р С‘РЎР‚РЎС“Р ВµРЎвЂљРЎРѓРЎРЏ Р Р† РЎвЂљР ВµР В»Р ВµР С–РЎР‚Р В°Р СРІР‚вЂР С”Р В°Р Р…Р В°Р В»Р Вµ Р’В«Р СњР С•Р Р†Р С•РЎРѓРЎвЂљР С‘Р’В»?\n"
                    "A) 5\nB) 10\nC) 15\nD) 30"
                ),
                correct_answer="C",
                explanation=None,
                concept_tag="start_s4_q2",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р С™Р В°Р С” Р Р…РЎС“Р В¶Р Р…Р С• Р С—Р С•Р Т‘Р С”Р В»РЎР‹РЎвЂЎР В°РЎвЂљРЎРЉРЎРѓРЎРЏ Р С—Р С• РЎР‚Р ВµР С–Р В»Р В°Р СР ВµР Р…РЎвЂљРЎС“?\n"
                    "A) Р вЂР ВµР В· Р С•Р С—Р С•Р В·Р Т‘Р В°Р Р…Р С‘Р в„–\nB) Р СљР С•Р В¶Р Р…Р С• Р С•Р С—Р С•Р В·Р Т‘Р В°РЎвЂљРЎРЉ\nC) Р СљР С•Р В¶Р Р…Р С• Р Р…Р Вµ Р С—РЎР‚Р С‘РЎвЂ¦Р С•Р Т‘Р С‘РЎвЂљРЎРЉ\nD) Р СџР С• Р В¶Р ВµР В»Р В°Р Р…Р С‘РЎР‹"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s4_q3",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.multi,
                difficulty=2,
                prompt=(
                    "Р вЂ™РЎвЂ№Р В±Р ВµРЎР‚Р С‘ Р С—РЎР‚Р В°Р Р†Р С‘Р В»Р В° РЎС“Р Р†Р В°Р В¶Р С‘РЎвЂљР ВµР В»РЎРЉР Р…Р С•Р С–Р С• РЎС“РЎвЂЎР В°РЎРѓРЎвЂљР С‘РЎРЏ (Р С•РЎвЂљР Р†Р ВµРЎвЂљ Р В±РЎС“Р С”Р Р†Р В°Р СР С‘, Р С—РЎР‚Р С‘Р СР ВµРЎР‚: ABD).\n"
                    "A) Р вЂњР С•Р Р†Р С•РЎР‚Р С‘РЎвЂљРЎРЉ Р С—Р С• Р С•Р Т‘Р Р…Р С•Р СРЎС“, Р Р…Р Вµ Р С—Р ВµРЎР‚Р ВµР В±Р С‘Р Р†Р В°РЎРЏ\nB) Р ВР В·Р В±Р ВµР С–Р В°РЎвЂљРЎРЉ Р С–РЎР‚РЎС“Р В±Р С•РЎРѓРЎвЂљР С‘\nC) Р СњР Вµ Р В·Р В°Р Т‘Р В°Р Р†Р В°РЎвЂљРЎРЉ Р Р†Р С•Р С—РЎР‚Р С•РЎРѓРЎвЂ№\nD) Р С’Р С”РЎвЂљР С‘Р Р†Р Р…Р С• РЎС“РЎвЂЎР В°РЎРѓРЎвЂљР Р†Р С•Р Р†Р В°РЎвЂљРЎРЉ"
                ),
                correct_answer="A,B,D",
                explanation=None,
                concept_tag="start_s4_q4",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р В§РЎвЂљР С• Р СР С•Р В¶Р ВµРЎвЂљ РЎРѓР Т‘Р ВµР В»Р В°РЎвЂљРЎРЉ РЎРѓР С—Р С‘Р С”Р ВµРЎР‚ Р С—РЎР‚Р С‘ Р Р…Р ВµР С”Р С•РЎР‚РЎР‚Р ВµР С”РЎвЂљР Р…Р С•Р С Р С—Р С•Р Р†Р ВµР Т‘Р ВµР Р…Р С‘Р С‘ РЎС“РЎвЂЎР В°РЎРѓРЎвЂљР Р…Р С‘Р С”Р В°?\n"
                    "A) Р вЂ”Р В°Р В±Р В»Р С•Р С”Р С‘РЎР‚Р С•Р Р†Р В°РЎвЂљРЎРЉ Р СР С‘Р С”РЎР‚Р С•РЎвЂћР С•Р Р…\nB) Р Р€Р Р†Р ВµР В»Р С‘РЎвЂЎР С‘РЎвЂљРЎРЉ Р С–РЎР‚Р С•Р СР С”Р С•РЎРѓРЎвЂљРЎРЉ\nC) Р С›РЎвЂљР СР ВµР Р…Р С‘РЎвЂљРЎРЉ Р Р†РЎРѓРЎвЂљРЎР‚Р ВµРЎвЂЎРЎС“ Р Р…Р В°Р Р†РЎРѓР ВµР С–Р Т‘Р В°\nD) Р вЂ™РЎвЂ№Р Т‘Р В°РЎвЂљРЎРЉ Р С—РЎР‚Р ВµР СР С‘РЎР‹"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s4_q5",
                variant_group=None,
            ),
        ]
    elif step == 5:
        q = [
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р В¤РЎР‚Р В°Р Р…РЎв‚¬Р С‘Р В·Р В° Р С™Р В°РЎР‚Р С”Р В°РЎРѓ Р СћР В°Р в„–Р С–Р С‘ РІР‚вЂќ РЎРЊРЎвЂљР С• Р’В«РЎР‚Р В°Р В±Р С•РЎвЂљР В° Р В·Р В° Р Р†Р В°РЎРѓР’В» Р С‘Р В»Р С‘ Р С—Р ВµРЎР‚Р ВµР Т‘Р В°РЎвЂЎР В° РЎРѓР С‘РЎРѓРЎвЂљР ВµР СРЎвЂ№/Р С‘Р Р…РЎРѓРЎвЂљРЎР‚РЎС“Р СР ВµР Р…РЎвЂљР С•Р Р†?\n"
                    "A) Р СџР ВµРЎР‚Р ВµР Т‘Р В°РЎвЂЎР В° РЎРѓР С‘РЎРѓРЎвЂљР ВµР СРЎвЂ№/Р С‘Р Р…РЎРѓРЎвЂљРЎР‚РЎС“Р СР ВµР Р…РЎвЂљР С•Р Р†\nB) Р В Р В°Р В±Р С•РЎвЂљР В° Р В·Р В° Р Р†Р В°РЎРѓ\nC) Р СњР С‘РЎвЂЎР ВµР С–Р С• Р Р…Р Вµ Р Т‘Р В°РЎвЂРЎвЂљ\nD) Р СћР С•Р В»РЎРЉР С”Р С• РЎР‚Р ВµР С”Р В»Р В°Р СР В°"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s5_q1",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.multi,
                difficulty=2,
                prompt=(
                    "Р В§РЎвЂљР С• Р С—Р В°РЎР‚РЎвЂљР Р…Р ВµРЎР‚ Р С—Р С•Р В»РЎС“РЎвЂЎР В°Р ВµРЎвЂљ Р С—Р С• РЎвЂћРЎР‚Р В°Р Р…РЎв‚¬Р С‘Р В·Р Вµ? (Р С•РЎвЂљР Р†Р ВµРЎвЂљ Р В±РЎС“Р С”Р Р†Р В°Р СР С‘, Р С—РЎР‚Р С‘Р СР ВµРЎР‚: ABD)\n"
                    "A) Р С›Р В±РЎС“РЎвЂЎР ВµР Р…Р С‘Р Вµ Р С‘ РЎРѓРЎвЂљР В°Р Р…Р Т‘Р В°РЎР‚РЎвЂљРЎвЂ№\nB) Р СљР В°РЎР‚Р С”Р ВµРЎвЂљР С‘Р Р…Р С–Р С•Р Р†РЎвЂ№Р Вµ Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»РЎвЂ№\nC) Р СћР С•Р В»РЎРЉР С”Р С• Р В»Р С•Р С–Р С•РЎвЂљР С‘Р С—\nD) Р СњР С•РЎС“РІР‚вЂРЎвЂ¦Р В°РЎС“ Р С‘ Р С”Р В°Р В»РЎРЉР С”РЎС“Р В»РЎРЏРЎвЂљР С•РЎР‚РЎвЂ№"
                ),
                correct_answer="A,B,D",
                explanation=None,
                concept_tag="start_s5_q2",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р СљР С•Р В¶Р Р…Р С• Р В»Р С‘ Р С—Р ВµРЎР‚Р ВµР Т‘Р В°Р Р†Р В°РЎвЂљРЎРЉ РЎвЂљРЎР‚Р ВµРЎвЂљРЎРЉР С‘Р С Р В»Р С‘РЎвЂ Р В°Р С Р В·Р В°Р С”РЎР‚РЎвЂ№РЎвЂљРЎвЂ№Р Вµ Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»РЎвЂ№/Р С”Р В°Р В»РЎРЉР С”РЎС“Р В»РЎРЏРЎвЂљР С•РЎР‚РЎвЂ№?\n"
                    "A) Р СљР С•Р В¶Р Р…Р С•\nB) Р вЂ”Р В°Р С—РЎР‚Р ВµРЎвЂ°Р В°Р ВµРЎвЂљРЎРѓРЎРЏ\nC) Р СљР С•Р В¶Р Р…Р С• РЎвЂљР С•Р В»РЎРЉР С”Р С• Р Т‘РЎР‚РЎС“Р В·РЎРЉРЎРЏР С\nD) Р СљР С•Р В¶Р Р…Р С• Р С—Р С•РЎРѓР В»Р Вµ Р С•Р С—Р В»Р В°РЎвЂљРЎвЂ№"
                ),
                correct_answer="B",
                explanation=None,
                concept_tag="start_s5_q3",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р С›РЎвЂљ РЎвЂЎРЎРЉР ВµР С–Р С• Р С‘Р СР ВµР Р…Р С‘ Р Т‘Р С•Р В»Р В¶Р Р…РЎвЂ№ Р Р†Р ВµРЎРѓРЎвЂљР С‘РЎРѓРЎРЉ РЎР‚Р ВµР С”Р В»Р В°Р СР Р…РЎвЂ№Р Вµ Р С”Р В°Р СР С—Р В°Р Р…Р С‘Р С‘ Р С—Р С• РЎР‚Р ВµР С–Р В»Р В°Р СР ВµР Р…РЎвЂљРЎС“?\n"
                    "A) Р С›РЎвЂљ Р С‘Р СР ВµР Р…Р С‘ РЎР‹РЎР‚Р В»Р С‘РЎвЂ Р В°\nB) Р С›РЎвЂљ Р С‘Р СР ВµР Р…Р С‘ РЎвЂћР С‘Р В·Р В»Р С‘РЎвЂ Р В°\nC) Р С›РЎвЂљ Р С‘Р СР ВµР Р…Р С‘ Р С—Р С•Р Т‘РЎР‚РЎРЏР Т‘РЎвЂЎР С‘Р С”Р В°\nD) Р С›РЎвЂљ Р С‘Р СР ВµР Р…Р С‘ Р С”Р С•Р Р…Р С”РЎС“РЎР‚Р ВµР Р…РЎвЂљР В°"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s5_q4",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р С™Р С•Р СРЎС“ Р СР С•Р В¶Р Р…Р С• Р С•Р В±РЎР‚Р В°РЎвЂ°Р В°РЎвЂљРЎРЉРЎРѓРЎРЏ Р С—Р С• Р Р†Р С•Р С—РЎР‚Р С•РЎРѓР В°Р С (Р С—Р С• РЎвЂљР ВµР С”РЎРѓРЎвЂљРЎС“)?\n"
                    "A) Р вЂњР С•Р В»Р С•Р Р†Р Р…Р С•Р СРЎС“ Р С•РЎвЂћР С‘РЎРѓРЎС“\nB) Р РЋР В»РЎС“РЎвЂЎР В°Р в„–Р Р…РЎвЂ№Р С Р В»РЎР‹Р Т‘РЎРЏР С\nC) Р С™Р С•Р Р…Р С”РЎС“РЎР‚Р ВµР Р…РЎвЂљР В°Р С\nD) Р СњР С‘Р С”Р С•Р СРЎС“"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s5_q5",
                variant_group=None,
            ),
        ]
    elif step == 6:
        q = [
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р вЂ”Р В° Р С”Р В°Р С”Р С•Р в„– РЎРѓРЎР‚Р С•Р С” РЎР‚Р ВµР С”Р С•Р СР ВµР Р…Р Т‘Р С•Р Р†Р В°Р Р…Р С• Р С—РЎР‚Р С•Р в„–РЎвЂљР С‘ Р Р†РЎРѓР Вµ Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»РЎвЂ№?\n"
                    "A) 1 Р Р…Р ВµР Т‘Р ВµР В»РЎРЏ\nB) 2 Р Р…Р ВµР Т‘Р ВµР В»Р С‘\nC) 3 Р Р…Р ВµР Т‘Р ВµР В»Р С‘\nD) 3 Р СР ВµРЎРѓРЎРЏРЎвЂ Р В°"
                ),
                correct_answer="C",
                explanation=None,
                concept_tag="start_s6_q1",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р С™ Р С”Р С•Р СРЎС“ Р С•Р В±РЎР‚Р В°РЎвЂ°Р В°РЎвЂљРЎРЉРЎРѓРЎРЏ Р С—Р С• Р В»РЎР‹Р В±РЎвЂ№Р С Р Р†Р С•Р С—РЎР‚Р С•РЎРѓР В°Р С Р Р†Р С• Р Р†РЎР‚Р ВµР СРЎРЏ Р С•Р В±РЎС“РЎвЂЎР ВµР Р…Р С‘РЎРЏ?\n"
                    "A) Р В Р ВµР С–Р С‘Р С•Р Р…Р В°Р В»РЎРЉР Р…Р С•Р СРЎС“ Р Т‘Р С‘РЎР‚Р ВµР С”РЎвЂљР С•РЎР‚РЎС“\nB) Р РЋР В»РЎС“РЎвЂЎР В°Р в„–Р Р…РЎвЂ№Р С Р В»РЎР‹Р Т‘РЎРЏР С\nC) Р С™Р С•Р Р…Р С”РЎС“РЎР‚Р ВµР Р…РЎвЂљР В°Р С\nD) Р СњР С‘Р С”Р С•Р СРЎС“"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s6_q2",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.multi,
                difficulty=2,
                prompt=(
                    "Р вЂ™РЎвЂ№Р В±Р ВµРЎР‚Р С‘ 5 Р С—РЎР‚Р В°Р Р†Р С‘Р В» РЎС“РЎРѓР С—Р ВµРЎв‚¬Р Р…Р С•Р С–Р С• Р С—Р В°РЎР‚РЎвЂљР Р…РЎвЂРЎР‚Р В° (Р С•РЎвЂљР Р†Р ВµРЎвЂљ Р В±РЎС“Р С”Р Р†Р В°Р СР С‘, Р С—РЎР‚Р С‘Р СР ВµРЎР‚: ABDE).\n"
                    "A) Р вЂРЎвЂ№РЎвЂљРЎРЉ Р С•РЎвЂљР С”РЎР‚РЎвЂ№РЎвЂљРЎвЂ№Р С Р С” Р Р…Р С•Р Р†Р С•Р СРЎС“\nB) Р вЂќР ВµРЎР‚Р В¶Р В°РЎвЂљРЎРЉ Р Р†РЎвЂ№РЎРѓР С•Р С”Р С‘Р в„– РЎвЂљР ВµР СР С—\nC) Р РЋР С”РЎР‚РЎвЂ№Р Р†Р В°РЎвЂљРЎРЉ Р С—РЎР‚Р С•Р В±Р В»Р ВµР СРЎвЂ№\nD) Р ВРЎРѓР С—Р С•Р В»РЎРЉР В·Р С•Р Р†Р В°РЎвЂљРЎРЉ Р С”Р С•Р СР В°Р Р…Р Т‘РЎС“ РЎРЊР С”РЎРѓР С—Р ВµРЎР‚РЎвЂљР С•Р Р†\nE) Р вЂќРЎС“Р СР В°РЎвЂљРЎРЉ Р С”Р В°Р С” Р С—РЎР‚Р ВµР Т‘Р С—РЎР‚Р С‘Р Р…Р С‘Р СР В°РЎвЂљР ВµР В»РЎРЉ"
                ),
                correct_answer="A,B,D,E",
                explanation=None,
                concept_tag="start_s6_q3",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р СљР С•Р В¶Р Р…Р С• Р В»Р С‘ Р В·Р В°Р С—РЎС“РЎРѓР С”Р В°РЎвЂљРЎРЉ РЎвЂљР ВµРЎРѓРЎвЂљР С•Р Р†РЎС“РЎР‹ РЎР‚Р ВµР С”Р В»Р В°Р СРЎС“ Р Р†Р С• Р Р†РЎР‚Р ВµР СРЎРЏ Р С•Р В±РЎС“РЎвЂЎР ВµР Р…Р С‘РЎРЏ?\n"
                    "A) Р вЂќР В°\nB) Р СњР ВµРЎвЂљ\nC) Р СћР С•Р В»РЎРЉР С”Р С• Р С—Р С• Р С—РЎР‚Р В°Р В·Р Т‘Р Р…Р С‘Р С”Р В°Р С\nD) Р СћР С•Р В»РЎРЉР С”Р С• Р С—Р С•РЎРѓР В»Р Вµ РЎРЊР С”Р В·Р В°Р СР ВµР Р…Р В°"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s6_q4",
                variant_group=None,
            ),
            Question(
                quiz_id=quiz_id,
                type=QuestionType.single,
                difficulty=1,
                prompt=(
                    "Р вЂўРЎРѓР В»Р С‘ РЎвЂЎРЎвЂљР С•-РЎвЂљР С• Р Р…Р Вµ РЎС“РЎРѓРЎвЂљРЎР‚Р В°Р С‘Р Р†Р В°Р ВµРЎвЂљ Р Р† Р С—Р С•Р Т‘Р Т‘Р ВµРЎР‚Р В¶Р С”Р Вµ, РЎвЂЎРЎвЂљР С• Р СР С•Р В¶Р Р…Р С• РЎРѓР Т‘Р ВµР В»Р В°РЎвЂљРЎРЉ РЎРѓ Р В Р вЂќ?\n"
                    "A) Р вЂ”Р В°Р СР ВµР Р…Р С‘РЎвЂљРЎРЉ\nB) Р Р€Р Р†Р С•Р В»Р С‘РЎвЂљРЎРЉ Р Р†РЎРѓР ВµРЎвЂ¦\nC) Р вЂ”Р В°Р С”РЎР‚РЎвЂ№РЎвЂљРЎРЉ Р С—РЎР‚Р С•Р ВµР С”РЎвЂљ\nD) Р СњР С‘РЎвЂЎР ВµР С–Р С•"
                ),
                correct_answer="A",
                explanation=None,
                concept_tag="start_s6_q5",
                variant_group=None,
            ),
        ]

    if not q:
        return

    for item in q:
        db.add(item)


def _parse_step_from_filename(filename: str) -> tuple[int | None, str]:
    base = pathlib.Path(filename).stem
    m = _STEP_RE.match(base)
    if not m:
        return None, base
    return int(m.group(1)), m.group(2)


def ensure_user(db, *, name: str, role: UserRole, password: str, position: str | None = None) -> User:
    existing = db.scalar(select(User).where(User.name == name))
    if existing is not None:
        return existing

    u = User(
        name=name,
        role=role,
        position=position,
        xp=0,
        level=1,
        streak=0,
        password_hash=pwd_context.hash(password),
        must_change_password=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def upload_file(*, path: pathlib.Path, object_key: str) -> tuple[str | None, int | None]:
    ensure_bucket_exists()
    s3 = get_s3_client()

    content_type, _ = mimetypes.guess_type(str(path))
    data = path.read_bytes()

    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=object_key,
        Body=data,
        ContentType=content_type or "application/octet-stream",
    )

    return content_type, len(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import 'Start' module content into CoreLMS (Postgres + MinIO)")
    parser.add_argument(
        "--path",
        default="/app/Модули обучения/1. Старт",
        help="Path to folder with Start module files",
    )
    parser.add_argument("--module-title", default="Старт")
    parser.add_argument("--admin-name", default=os.environ.get("CORELMS_SEED_ADMIN_NAME", "admin"))
    parser.add_argument("--admin-password", default=os.environ.get("CORELMS_SEED_ADMIN_PASSWORD", "admin"))
    parser.add_argument("--employee-name", default=os.environ.get("CORELMS_SEED_EMPLOYEE_NAME", "employee"))
    parser.add_argument("--employee-password", default=os.environ.get("CORELMS_SEED_EMPLOYEE_PASSWORD", "employee"))
    args = parser.parse_args()

    folder = pathlib.Path(args.path)

    # In Docker images used for pilots, training content may be mounted later or
    # not shipped with the backend image at all. The platform must still boot.
    has_folder = folder.exists() and folder.is_dir()
    files: list[pathlib.Path] = []
    if has_folder:
        files = [p for p in sorted(folder.iterdir()) if p.is_file()]

    with SessionLocal() as db:
        admin = ensure_user(db, name=args.admin_name, role=UserRole.admin, password=args.admin_password)
        ensure_user(db, name=args.employee_name, role=UserRole.employee, password=args.employee_password)

        # In many production deployments (Railway), the backend image does not ship training content.
        # In this case we must not create placeholder modules with broken encoding.
        allow_placeholder = (os.environ.get("CORELMS_SEED_ALLOW_PLACEHOLDER_MODULE") or "").strip().lower() in {"1", "true", "yes", "on"}
        if not has_folder and not allow_placeholder:
            print(f"Folder not found: {folder}")
            print("Skipping Start module import; users ensured.")
            print("Users created/ensured:")
            print(f"  admin: {args.admin_name} / {args.admin_password}")
            print(f"  employee: {args.employee_name} / {args.employee_password}")
            return

        module = db.scalar(select(Module).where(Module.title == args.module_title))
        if module is None:
            module = Module(
                title=args.module_title, 
                description="Основы работы, оргструктура и регламенты компании.", 
                difficulty=1, 
                category="Onboarding", 
                is_active=True
            )
            db.add(module)
            db.commit()
            db.refresh(module)

        if not has_folder:
            existing = db.scalars(select(Submodule).where(Submodule.module_id == module.id).order_by(Submodule.order)).all()
            if not existing:
                titles = ["Р вЂ™Р Р†Р ВµР Т‘Р ВµР Р…Р С‘Р Вµ", "Р СџРЎР‚Р С•РЎвЂ Р ВµРЎРѓРЎРѓ Р С•Р В±РЎС“РЎвЂЎР ВµР Р…Р С‘РЎРЏ", "Р В¤Р С‘Р Р…Р В°Р В»РЎРЉР Р…Р В°РЎРЏ Р С—РЎР‚Р С•Р Р†Р ВµРЎР‚Р С”Р В°"]
                order = 1
                for title in titles:
                    quiz = Quiz(type=QuizType.submodule, pass_threshold=70, time_limit=600, attempts_limit=3)
                    db.add(quiz)
                    db.flush()

                    db.add(
                        Question(
                            quiz_id=quiz.id,
                            type=QuestionType.single,
                            difficulty=1,
                            prompt="Р СџР С•Р Т‘РЎвЂљР Р†Р ВµРЎР‚Р Т‘Р С‘ Р С—РЎР‚Р С•РЎвЂ¦Р С•Р В¶Р Т‘Р ВµР Р…Р С‘Р Вµ: Р Р†Р Р†Р ВµР Т‘Р С‘ РЎРѓР В»Р С•Р Р†Р С• Р СџР В Р С›Р В§Р ВР СћР С’Р вЂє",
                            correct_answer="Р СџР В Р С›Р В§Р ВР СћР С’Р вЂє",
                            explanation=None,
                            concept_tag="start_ack",
                            variant_group=None,
                        )
                    )

                    db.add(Submodule(module_id=module.id, title=title, content="", order=order, quiz_id=quiz.id))
                    order += 1

                final_quiz = Quiz(type=QuizType.final, pass_threshold=70, time_limit=900, attempts_limit=2)
                db.add(final_quiz)
                db.flush()
                if getattr(module, "final_quiz_id", None) is None:
                    module.final_quiz_id = final_quiz.id
                db.add(
                    Question(
                        quiz_id=final_quiz.id,
                        type=QuestionType.case,
                        difficulty=2,
                        prompt="Р С™Р ВµР в„–РЎРѓ: Р С•Р С—Р С‘РЎв‚¬Р С‘ Р С”Р В»РЎР‹РЎвЂЎР ВµР Р†РЎвЂ№Р Вµ Р Р†РЎвЂ№Р Р†Р С•Р Т‘РЎвЂ№ Р С‘Р В· Р СР С•Р Т‘РЎС“Р В»РЎРЏ (1 РЎРѓРЎвЂљРЎР‚Р С•Р С”Р В°).",
                        correct_answer="",
                        explanation="",
                        concept_tag="start_case",
                        variant_group=None,
                    )
                )
                db.commit()

            print(f"Folder not found: {folder}")
            print("Skipping content import; placeholder submodules ensured.")
            print("Users created/ensured:")
            print(f"  admin: {args.admin_name} / {args.admin_password}")
            print(f"  employee: {args.employee_name} / {args.employee_password}")
            return

        if not files:
            print(f"No files in folder: {folder}")
            print("Skipping file import; demo users ensured.")
            print("Users created/ensured:")
            print(f"  admin: {args.admin_name} / {args.admin_password}")
            print(f"  employee: {args.employee_name} / {args.employee_password}")
            return

        # Ideal import: group multiple files under the same learning step.
        grouped: dict[int, list[pathlib.Path]] = {}
        step_titles: dict[int, str] = {}
        for f in files:
            step, title = _parse_step_from_filename(f.name)
            if step is None:
                continue
            grouped.setdefault(step, []).append(f)
            step_titles.setdefault(step, title)

        for order in sorted(grouped.keys()):
            title = step_titles.get(order) or f"Р РЃР В°Р С– {order}"
            sub_title = f"{order}. {title}"

            sub = db.scalar(
                select(Submodule).where(Submodule.module_id == module.id, Submodule.order == order)
            )
            
            # Р СџР С•Р С—РЎвЂ№РЎвЂљР С”Р В° Р Р…Р В°Р в„–РЎвЂљР С‘ РЎвЂљР ВµР С”РЎРѓРЎвЂљР С•Р Р†РЎвЂ№Р в„– РЎвЂћР В°Р в„–Р В» Р Т‘Р В»РЎРЏ Р С”Р С•Р Р…РЎвЂљР ВµР Р…РЎвЂљР В° Р С—Р С•Р Т‘Р СР С•Р Т‘РЎС“Р В»РЎРЏ
            content_text = ""
            txt_files = [f for f in grouped[order] if f.suffix.lower() == ".txt"]
            if txt_files:
                try:
                    content_text = txt_files[0].read_text(encoding="utf-8")
                except Exception as e:
                    print(f"Error reading {txt_files[0]}: {e}")

            if sub is None:
                quiz = Quiz(type=QuizType.submodule, pass_threshold=70, time_limit=600, attempts_limit=3)
                db.add(quiz)
                db.flush()

                sub = Submodule(module_id=module.id, title=sub_title, content=content_text, order=order, quiz_id=quiz.id)
                db.add(sub)
                db.flush()
            else:
                if sub.title != sub_title:
                    sub.title = sub_title
                if content_text:
                    sub.content = content_text
                quiz = db.scalar(select(Quiz).where(Quiz.id == sub.quiz_id))

                # If the submodule already has a quiz from an older import/template, do not mutate it.
                # Create a fresh quiz and rebind the submodule to it, so learners see the correct questions.
                if quiz is not None:
                    has_our_questions = db.scalar(
                        select(Question.id)
                        .where(
                            Question.quiz_id == quiz.id,
                            Question.concept_tag.like(f"start_s{order}_%"),
                        )
                        .limit(1)
                    )
                    if has_our_questions is None:
                        new_quiz = Quiz(type=QuizType.submodule, pass_threshold=70, time_limit=600, attempts_limit=3)
                        db.add(new_quiz)
                        db.flush()
                        sub.quiz_id = new_quiz.id
                        quiz = new_quiz

            if quiz is not None:
                has_q = db.scalar(select(Question.id).where(Question.quiz_id == quiz.id).limit(1))
                if has_q is None:
                    db.add(
                        Question(
                            quiz_id=quiz.id,
                            type=QuestionType.single,
                            difficulty=1,
                            prompt=f"Р СџР С•Р Т‘РЎвЂљР Р†Р ВµРЎР‚Р Т‘Р С‘, РЎвЂЎРЎвЂљР С• Р С‘Р В·РЎС“РЎвЂЎР С‘Р В» Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»РЎвЂ№ РЎв‚¬Р В°Р С–Р В° Р’В«{sub_title}Р’В». Р вЂ™Р Р†Р ВµР Т‘Р С‘ РЎРѓР В»Р С•Р Р†Р С•: Р СџР В Р С›Р В§Р ВР СћР С’Р вЂє",
                            correct_answer="Р СџР В Р С›Р В§Р ВР СћР С’Р вЂє",
                            explanation=None,
                            concept_tag="start_ack",
                            variant_group=None,
                        )
                    )

                _upsert_step_quiz_questions(db=db, quiz_id=quiz.id, step=order, sub_title=sub_title)

            step_files = sorted(grouped[order], key=lambda p: p.name)
            for f in step_files:
                object_key = f"modules/start/{order:02d}/{slugify(f.name)}"

                asset = db.scalar(select(ContentAsset).where(ContentAsset.object_key == object_key))
                if asset is None:
                    mime_type, size_bytes = upload_file(path=f, object_key=object_key)
                    asset = ContentAsset(
                        bucket=settings.s3_bucket,
                        object_key=object_key,
                        original_filename=f.name,
                        mime_type=mime_type,
                        size_bytes=size_bytes,
                        checksum_sha256=None,
                        version=1,
                        created_by=admin.id,
                    )
                    db.add(asset)
                    db.flush()

                link = db.scalar(
                    select(SubmoduleAssetMap).where(
                        SubmoduleAssetMap.submodule_id == sub.id,
                        SubmoduleAssetMap.asset_id == asset.id,
                    )
                )
                if link is None:
                    max_order = db.scalar(
                        select(func.coalesce(func.max(SubmoduleAssetMap.order), 0)).where(
                            SubmoduleAssetMap.submodule_id == sub.id
                        )
                    )
                    db.add(
                        SubmoduleAssetMap(
                            submodule_id=sub.id,
                            asset_id=asset.id,
                            order=int(max_order) + 1,
                        )
                    )

        # Final quiz is optional; avoid duplicating it on re-import.
        final_quiz_id = db.scalar(select(Question.quiz_id).where(Question.concept_tag == "start_case").limit(1))
        if final_quiz_id is None:
            final_quiz = Quiz(type=QuizType.final, pass_threshold=75, time_limit=1200, attempts_limit=2)
            db.add(final_quiz)
            db.flush()

            # Final certification quiz: 10 questions across all steps
            final_questions: list[Question] = [
                Question(
                    quiz_id=final_quiz.id,
                    type=QuestionType.multi,
                    difficulty=2,
                    prompt=(
                        "Р вЂ™РЎвЂ№Р В±Р ВµРЎР‚Р С‘ Р С”Р В»РЎР‹РЎвЂЎР ВµР Р†РЎвЂ№Р Вµ РЎРЊР В»Р ВµР СР ВµР Р…РЎвЂљРЎвЂ№ РЎРѓР С‘РЎРѓРЎвЂљР ВµР СРЎвЂ№ РЎвЂћРЎР‚Р В°Р Р…РЎв‚¬Р С‘Р В·РЎвЂ№ (Р С•РЎвЂљР Р†Р ВµРЎвЂљ Р В±РЎС“Р С”Р Р†Р В°Р СР С‘, Р С—РЎР‚Р С‘Р СР ВµРЎР‚: ABD).\n"
                        "A) Р РЋРЎвЂљР В°Р Р…Р Т‘Р В°РЎР‚РЎвЂљРЎвЂ№ Р С‘ Р С‘Р Р…РЎРѓРЎвЂљРЎР‚РЎС“Р С”РЎвЂ Р С‘Р С‘\nB) Р СњР С•РЎС“РІР‚вЂРЎвЂ¦Р В°РЎС“ Р С‘ Р С‘Р Р…РЎРѓРЎвЂљРЎР‚РЎС“Р СР ВµР Р…РЎвЂљРЎвЂ№\nC) Р вЂ™РЎвЂ№Р С—Р С•Р В»Р Р…Р ВµР Р…Р С‘Р Вµ РЎР‚Р В°Р В±Р С•РЎвЂљРЎвЂ№ Р В·Р В° Р С—Р В°РЎР‚РЎвЂљР Р…РЎвЂРЎР‚Р В°\nD) Р СџР С•Р Т‘Р Т‘Р ВµРЎР‚Р В¶Р С”Р В° РЎРѓР С—Р ВµРЎвЂ Р С‘Р В°Р В»Р С‘РЎРѓРЎвЂљР С•Р Р†"
                    ),
                    correct_answer="A,B,D",
                    explanation=None,
                    concept_tag="start_final_q1",
                    variant_group=None,
                ),
                Question(
                    quiz_id=final_quiz.id,
                    type=QuestionType.single,
                    difficulty=1,
                    prompt="Р В§РЎвЂљР С• Р Р†Р В°Р В¶Р Р…Р С• Р Р†РЎвЂ№Р В±РЎР‚Р В°РЎвЂљРЎРЉ Р С—РЎР‚Р С‘ РЎР‚Р ВµР С–Р С‘РЎРѓРЎвЂљРЎР‚Р В°РЎвЂ Р С‘Р С‘ Р В±Р С‘Р В·Р Р…Р ВµРЎРѓР В° (Р С”Р В»РЎР‹РЎвЂЎР ВµР Р†Р С•Р в„– РЎвЂљР ВµРЎР‚Р СР С‘Р Р… Р С‘Р В· РЎв‚¬Р В°Р С–Р В° 1)?",
                    correct_answer="Р С›Р С™Р вЂ™Р В­Р вЂќ",
                    explanation=None,
                    concept_tag="start_final_q2",
                    variant_group=None,
                ),
                Question(
                    quiz_id=final_quiz.id,
                    type=QuestionType.single,
                    difficulty=1,
                    prompt="Р С™РЎвЂљР С• РЎР‚Р В°РЎРѓР С—РЎР‚Р ВµР Т‘Р ВµР В»РЎРЏР ВµРЎвЂљ Р В»Р С‘Р Т‘РЎвЂ№ Р СР ВµР В¶Р Т‘РЎС“ Р СР ВµР Р…Р ВµР Т‘Р В¶Р ВµРЎР‚Р В°Р СР С‘?",
                    correct_answer="Р С™Р В»Р В°РЎРѓРЎРѓР С‘РЎвЂћР С‘Р С”Р В°РЎвЂљР С•РЎР‚ Р В»Р С‘Р Т‘Р С•Р Р†",
                    explanation=None,
                    concept_tag="start_final_q3",
                    variant_group=None,
                ),
                Question(
                    quiz_id=final_quiz.id,
                    type=QuestionType.single,
                    difficulty=1,
                    prompt="Р вЂ”Р В° РЎРѓР С”Р С•Р В»РЎРЉР С”Р С• Р СР С‘Р Р…РЎС“РЎвЂљ Р Т‘Р С• Р Р…Р В°РЎвЂЎР В°Р В»Р В° Р Р†РЎРѓРЎвЂљРЎР‚Р ВµРЎвЂЎР С‘ РЎРѓРЎРѓРЎвЂ№Р В»Р С”Р В° Р Т‘РЎС“Р В±Р В»Р С‘РЎР‚РЎС“Р ВµРЎвЂљРЎРѓРЎРЏ Р Р† Р’В«Р СњР С•Р Р†Р С•РЎРѓРЎвЂљР С‘Р’В»?",
                    correct_answer="15",
                    explanation=None,
                    concept_tag="start_final_q4",
                    variant_group=None,
                ),
                Question(
                    quiz_id=final_quiz.id,
                    type=QuestionType.single,
                    difficulty=1,
                    prompt="Р вЂ”Р В° Р С”Р В°Р С”Р С•Р в„– РЎРѓРЎР‚Р С•Р С” РЎР‚Р ВµР С”Р С•Р СР ВµР Р…Р Т‘Р С•Р Р†Р В°Р Р…Р С• Р С—РЎР‚Р С•Р в„–РЎвЂљР С‘ Р Р†РЎРѓР Вµ Р СР В°РЎвЂљР ВµРЎР‚Р С‘Р В°Р В»РЎвЂ№ РЎРѓРЎвЂљР В°РЎР‚РЎвЂљР С•Р Р†Р С•Р С–Р С• Р СР С•Р Т‘РЎС“Р В»РЎРЏ?",
                    correct_answer="3 Р Р…Р ВµР Т‘Р ВµР В»Р С‘",
                    explanation=None,
                    concept_tag="start_final_q5",
                    variant_group=None,
                ),
                Question(
                    quiz_id=final_quiz.id,
                    type=QuestionType.case,
                    difficulty=2,
                    prompt="Р С™Р ВµР в„–РЎРѓ: Р С•Р С—Р С‘РЎв‚¬Р С‘ Р С•Р Т‘Р Р…Р С•Р в„– РЎРѓРЎвЂљРЎР‚Р С•Р С”Р С•Р в„–, Р С—Р С•РЎвЂЎР ВµР СРЎС“ Р Р†Р В°Р В¶Р Р…Р С• РЎРѓР С•Р В±Р В»РЎР‹Р Т‘Р В°РЎвЂљРЎРЉ РЎРѓРЎвЂљР В°Р Р…Р Т‘Р В°РЎР‚РЎвЂљРЎвЂ№ Р С‘ РЎР‚Р ВµР С–Р В»Р В°Р СР ВµР Р…РЎвЂљРЎвЂ№ Р С”Р С•Р СР С—Р В°Р Р…Р С‘Р С‘.",
                    correct_answer="ANY",
                    explanation=None,
                    concept_tag="start_final_case1",
                    variant_group=None,
                ),
                Question(
                    quiz_id=final_quiz.id,
                    type=QuestionType.case,
                    difficulty=2,
                    prompt="Р С™Р ВµР в„–РЎРѓ: Р Р…Р В°Р С—Р С‘РЎв‚¬Р С‘ 3 Р Т‘Р ВµР в„–РЎРѓРЎвЂљР Р†Р С‘РЎРЏ, Р С”Р С•РЎвЂљР С•РЎР‚РЎвЂ№Р Вµ РЎвЂљРЎвЂ№ РЎРѓР Т‘Р ВµР В»Р В°Р ВµРЎв‚¬РЎРЉ Р Р† Р С—Р ВµРЎР‚Р Р†РЎвЂ№Р Вµ 7 Р Т‘Р Р…Р ВµР в„– Р С—Р С•РЎРѓР В»Р Вµ РЎРѓРЎвЂљР В°РЎР‚РЎвЂљР В° (1 РЎРѓРЎвЂљРЎР‚Р С•Р С”Р В°).",
                    correct_answer="ANY",
                    explanation=None,
                    concept_tag="start_case",
                    variant_group=None,
                ),
            ]
            for qq in final_questions:
                db.add(qq)

            final_quiz_id = final_quiz.id

        # Ensure module points to the final quiz even on re-import.
        if getattr(module, "final_quiz_id", None) != final_quiz_id:
            module.final_quiz_id = final_quiz_id
            db.execute(update(Module).where(Module.id == module.id).values(final_quiz_id=final_quiz_id))

        db.commit()

    print("Imported module 'Р РЋРЎвЂљР В°РЎР‚РЎвЂљ' successfully")
    print("Users created/ensured:")
    print(f"  admin: {args.admin_name} / {args.admin_password}")
    print(f"  employee: {args.employee_name} / {args.employee_password}")


if __name__ == "__main__":
    main()
