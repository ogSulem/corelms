"""Structured quiz authoring and explicitly reviewable AI drafts, never auto-publish."""
from __future__ import annotations

import re
import hashlib
import json
import io
import logging
import uuid
from types import SimpleNamespace

from sqlalchemy import case, select
from rq import get_current_job
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models.asset import ContentAsset
from app.models.module import Module, Submodule
from app.models.quiz import Question, Quiz
from app.models.submodule_asset import SubmoduleAssetMap
from app.schemas.authoring import QuestionDraft
from app.services.content import read_lesson_text
from app.services.document_preview import MAX_BYTES, build_preview, preview_slot
from app.services.llm_handler import generate_quiz_questions_ai
from app.services.media import current_rendition
from app.services.quiz_text import is_useful_quiz_text
from app.services.storage import get_s3_client

log = logging.getLogger(__name__)

LETTER_MAP = str.maketrans("АБВГД", "ABCDE")


def question_payload(question) -> dict:
    """Translate the legacy prompt-with-options format without inventing answers."""
    stem, options = [], {}
    current = None
    malformed = False
    for line in str(question.prompt).splitlines():
        match = re.match(r"^\s*([A-EАБВГД])[).:]\s*(.*)$", line, re.I)
        if match:
            current = match[1].upper().translate(LETTER_MAP)
            if current in options:
                malformed = True
                current = None
                break
            options[current] = match[2].strip()
        elif current:
            options[current] += "\n" + line
        else:
            stem.append(line)
    ordered = sorted(options)
    qtype = str(getattr(question.type, "value", question.type))
    answer = str(question.correct_answer or "").upper().translate(LETTER_MAP).strip()
    letters = re.findall(r"[A-E]", answer) if re.fullmatch(r"[A-E\s,;]+", answer) else []
    valid = not malformed and ordered == list("ABCDE"[:len(ordered)]) and len(set(letters)) == len(letters)
    data = {"id": str(question.id) if getattr(question, "id", None) else None, "type": qtype,
        "stem": "\n".join(stem).strip() or str(question.prompt), "options": [options[k].strip() for k in ordered],
        "correct": [ord(k) - 65 for k in sorted(letters)], "explanation": getattr(question, "explanation", None) or ""}
    try:
        QuestionDraft.model_validate(data)
    except ValidationError:
        valid = False
    return {**data, "valid": valid}


def source_revision(db, lesson: Submodule) -> str:
    """Only changes relevant to this lesson invalidate a reviewed AI draft.

    Quiz edits, module publication, a different lesson and completed renditions
    do not change the immutable source identity.
    """
    assets = list(db.execute(select(ContentAsset, SubmoduleAssetMap.order)
        .join(SubmoduleAssetMap, SubmoduleAssetMap.asset_id == ContentAsset.id)
        .where(SubmoduleAssetMap.submodule_id == lesson.id, ContentAsset.is_archived.is_(False))
        .order_by(case((ContentAsset.id == lesson.primary_asset_id, 0), else_=1), SubmoduleAssetMap.order, ContentAsset.id).limit(5)))
    value = {
        "version": 1, "module": str(lesson.module_id), "lesson": str(lesson.id), "title": lesson.title,
        "text": hashlib.sha256((lesson.content or "").encode()).hexdigest(), "text_version": lesson.content_version,
        "text_key": lesson.content_object_key, "presentation": lesson.presentation_mode,
        "primary": str(lesson.primary_asset_id) if lesson.primary_asset_id else None,
        "archived": lesson.is_archived, "folder": lesson.is_folder,
        "assets": [(str(asset.id), asset.version, asset.bucket, asset.object_key, asset.original_filename,
                    asset.checksum_sha256, position) for asset, position in assets],
    }
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def request_signature(source: str, count: int, text: str | None = None) -> str:
    return hashlib.sha256(json.dumps([source, count, text], ensure_ascii=False).encode()).hexdigest()


def quiz_payload(db, module: Module, lesson: Submodule) -> dict:
    quiz = db.get(Quiz, lesson.quiz_id)
    questions = list(db.scalars(select(Question).where(Question.quiz_id == quiz.id).order_by(Question.position, Question.id)))
    return {"revision": module.content_revision, "source_revision": source_revision(db, lesson), "lesson_id": str(lesson.id), "quiz_id": str(quiz.id),
            "enabled": lesson.requires_quiz, "pass_threshold": quiz.pass_threshold,
            "time_limit": quiz.time_limit, "attempts_limit": quiz.attempts_limit,
            "questions": [question_payload(q) for q in questions]}


def format_prompt(question: QuestionDraft) -> str:
    return question.stem + "\n" + "\n".join(f"{'ABCDE'[i]}) {text}" for i, text in enumerate(question.options))


def _source_text(db, lesson: Submodule) -> tuple[str, str]:
    text = read_lesson_text(lesson.content, lesson.content_object_key).strip()
    if lesson.presentation_mode == "text" and is_useful_quiz_text(text):
        return text[:60000], "Текст урока (открывается первым)"
    assets = list(db.scalars(select(ContentAsset).join(SubmoduleAssetMap, SubmoduleAssetMap.asset_id == ContentAsset.id)
        .where(SubmoduleAssetMap.submodule_id == lesson.id, ContentAsset.is_archived.is_(False))
        .order_by(case((ContentAsset.id == lesson.primary_asset_id, 0), else_=1), SubmoduleAssetMap.order, ContentAsset.id).limit(5)))
    for asset in assets:
        current = current_rendition(db, asset)
        if current and is_useful_quiz_text(current.text_content or ""):
            return current.text_content[:60000], f"Документ «{asset.original_filename}»"
        if asset.original_filename.rsplit(".", 1)[-1].lower() not in {"docx", "pptx", "pdf", "txt", "md"}:
            continue
        if asset.size_bytes and asset.size_bytes > MAX_BYTES:
            continue
        try:
            with preview_slot():
                obj = get_s3_client().get_object(Bucket=asset.bucket, Key=asset.object_key)
                body = obj["Body"]
                try:
                    raw = body.read(MAX_BYTES + 1)
                finally:
                    body.close()
                if len(raw) > MAX_BYTES:
                    continue
                if asset.original_filename.lower().endswith(".pdf"):
                    from pypdf import PdfReader
                    reader = PdfReader(io.BytesIO(raw))
                    chunks = []
                    for page in reader.pages[:20]:
                        chunks.append((page.extract_text() or "")[:60000])
                        if sum(len(t) for t in chunks) >= 60000:
                            break
                    extracted = "\n\n".join(chunks)[:60000]
                else:
                    preview = build_preview(raw, asset.original_filename)
                    extracted = preview.get("text") or "\n\n".join(p["text"] for p in preview.get("blocks", []))
            if is_useful_quiz_text(extracted):
                note = " · первые 20 страниц PDF, без OCR" if asset.original_filename.lower().endswith(".pdf") else ""
                return extracted[:60000], f"Документ «{asset.original_filename}»{note}"
        except Exception as exc:
            log.info("Quiz draft source unavailable (%s)", type(exc).__name__)
    return (text[:60000], "Конспект / текст урока") if is_useful_quiz_text(text) else ("", "Нет доступного текста")


def generate_quiz_draft_job(module_id: str, lesson_id: str, revision: int, count: int, source_text: str | None = None, source_fingerprint: str | None = None) -> dict:
    job = get_current_job()
    if job:
        job.meta.update(stage="draft_source", module_id=module_id, lesson_id=lesson_id)
        job.save_meta()
    try:
        with SessionLocal() as db:
            module, lesson = db.get(Module, uuid.UUID(module_id)), db.get(Submodule, uuid.UUID(lesson_id))
            if (not module or not lesson or (not source_fingerprint and module.content_revision != revision) or lesson.module_id != module.id
                    or module.is_archived or lesson.is_archived or lesson.is_folder):
                return {"ok": False, "error": "Материалы изменены или недоступны. Обновите редактор и создайте новый черновик."}
            if source_fingerprint and source_revision(db, lesson) != source_fingerprint:
                return {"ok": False, "error": "Материалы этого урока изменены. Создайте новый черновик."}
            title = lesson.title
            text, source_label = (source_text.strip(), "Текст, вставленный автором") if source_text is not None else _source_text(db, lesson)
        if not is_useful_quiz_text(text):
            return {"ok": False, "error_code": "insufficient_source", "error": "Недостаточно содержательного текста. Добавьте конспект или вставьте текст для генерации. Видео автоматически не расшифровывается."}
        if job:
            job.refresh()
            if job.meta.get("cancel_requested"):
                return {"ok": False, "error": "Подготовка черновика отменена"}
            job.meta.update(stage="draft_generation")
            job.save_meta()
        source_length = len(text)
        text = text[:12000]  # Match the OpenRouter prompt budget; report the actual input.
        generated = generate_quiz_questions_ai(title=title, text=text[:60000], n_questions=count,
            min_questions=1, retries=1, time_budget_seconds=180)
        questions = []
        for question in generated or []:
            obj = SimpleNamespace(**question) if isinstance(question, dict) else question
            data = question_payload(obj)
            if data["valid"]:
                questions.append(data)
        if not questions:
            return {"ok": False, "error": "AI не вернул проверяемые вопросы. Ничего не опубликовано. Повторите позже или добавьте вопросы вручную."}
        return {"ok": True, "module_id": module_id, "lesson_id": lesson_id, "revision": revision,
                "questions": questions[:count], "source_revision": source_fingerprint, "needs_review": True, "source_label": source_label, "source_chars": len(text),
                "source_total_chars": source_length,
                "notice": "Использованы первые 12 000 символов источника. Для других разделов вставьте нужный фрагмент в поле генерации и добавьте новые вопросы к существующим." if source_length > 12000 else None}
    except Exception:
        return {"ok": False, "error": "Не удалось подготовить черновик. Проверьте текст и настройку AI-провайдера; действующий тест не изменён."}
