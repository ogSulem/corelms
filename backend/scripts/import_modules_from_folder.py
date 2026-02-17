from __future__ import annotations

import argparse
import mimetypes
import os
import pathlib
import random
import re
import sys
import uuid
import zipfile
from dataclasses import dataclass

from sqlalchemy import delete, select, text

# Ensure imports work when running from any CWD (Windows / local) and in Docker (/app)
_HERE = pathlib.Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, "/app")
sys.path.insert(0, os.getcwd())

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.asset import ContentAsset
from app.models.module import Module, Submodule
from app.models.quiz import Question, QuestionType, Quiz, QuizType
from app.models.submodule_asset import SubmoduleAssetMap
from app.services.storage import ensure_bucket_exists, get_s3_client


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9а-я._ -]+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ", "-")
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "module"


def _docx_to_text(path: pathlib.Path) -> str:
    try:
        with zipfile.ZipFile(path, "r") as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<[^>]+>", "", xml)
        xml = re.sub(r"\n{3,}", "\n\n", xml)
        return xml.strip()
    except Exception:
        return ""


def _pdf_to_text(path: pathlib.Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages[:30]:
            t = page.extract_text() or ""
            t = _clean_line(t)
            if t:
                parts.append(t)
        return "\n".join(parts).strip()
    except Exception:
        return ""


def _clean_line(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_facts(text: str) -> list[str]:
    """Extract candidate factual statements from raw lesson text.

    Heuristics:
    - Prefer numbered/bulleted lines.
    - Keep medium-length sentences.
    - Deduplicate.
    """

    if not text:
        return []

    lines = [
        _clean_line(x)
        for x in re.split(r"\r?\n", text)
        if _clean_line(x)
    ]

    picked: list[str] = []
    for ln in lines:
        if re.match(r"^(\d{1,2}|[\-•])\s*[.)\-]?\s+", ln):
            picked.append(re.sub(r"^(\d{1,2}|[\-•])\s*[.)\-]?\s+", "", ln).strip())

    # If not enough structured lines, fall back to any reasonable sentence-like lines.
    if len(picked) < 6:
        for ln in lines:
            if 25 <= len(ln) <= 170:
                picked.append(ln)

    # Normalize + dedupe
    uniq: list[str] = []
    seen: set[str] = set()
    for x in picked:
        x = _clean_line(x)
        if not x:
            continue
        key = x.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(x)

    # Keep only first N to avoid overly long pools
    return uniq[:40]


@dataclass
class _MCQ:
    prompt: str
    correct_answer: str
    qtype: QuestionType


def _format_mcq_prompt(*, stem: str, options: list[str]) -> str:
    letters = ["A", "B", "C", "D"]
    out = [stem.strip()]
    for i, opt in enumerate(options[:4]):
        out.append(f"{letters[i]}) {opt}")
    return "\n".join(out)


def _make_single_from_facts(*, title: str, facts: list[str], rng: random.Random) -> _MCQ | None:
    if len(facts) < 4:
        return None
    correct = rng.choice(facts)
    distractors = [x for x in facts if x != correct]
    rng.shuffle(distractors)
    opts = [correct] + distractors[:3]
    rng.shuffle(opts)
    correct_letter = ["A", "B", "C", "D"][opts.index(correct)]
    stem = f"Что из перечисленного относится к уроку «{title}»?"
    return _MCQ(prompt=_format_mcq_prompt(stem=stem, options=opts), correct_answer=correct_letter, qtype=QuestionType.single)


def _make_multi_from_facts(*, title: str, facts: list[str], rng: random.Random) -> _MCQ | None:
    if len(facts) < 6:
        return None
    rng.shuffle(facts)
    correct_set = facts[:2]
    distractors = facts[2:]
    opts = correct_set + distractors[:2]
    rng.shuffle(opts)
    letters = ["A", "B", "C", "D"]
    correct_letters = [letters[i] for i, o in enumerate(opts) if o in correct_set]
    correct_answer = ",".join(sorted(correct_letters))
    stem = f"Выберите верные утверждения по уроку «{title}» (ответ буквами, пример: A,C)."
    return _MCQ(prompt=_format_mcq_prompt(stem=stem, options=opts), correct_answer=correct_answer, qtype=QuestionType.multi)


def _read_text_from_file(path: pathlib.Path) -> str:
    ext = path.suffix.lower()
    if ext in {".txt", ".md"}:
        try:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return ""
    if ext == ".docx":
        return _docx_to_text(path)
    if ext == ".pdf":
        return _pdf_to_text(path)
    return ""


def _guess_title_from_filename(name: str) -> str:
    s = re.sub(r"^\s*\d+\s*[.)_-]*\s*", "", name)
    s = re.sub(r"\.[a-zA-Z0-9]+$", "", s)
    return s.strip() or name


def _parse_order(name: str, fallback: int) -> int:
    m = re.match(r"^\s*(\d{1,3})", (name or "").strip())
    if not m:
        return fallback
    try:
        v = int(m.group(1))
        return v if v > 0 else fallback
    except Exception:
        return fallback


def _extract_theory_from_lesson_files(files: list[pathlib.Path]) -> str:
    """Pick best-effort theory text from a lesson folder.

    Priority:
    - docx
    - pdf
    - txt/md
    If multiple exist, concatenates small pieces (keeps it readable).
    """

    if not files:
        return ""

    # Prefer text-bearing formats
    preferred = []
    for ext in (".docx", ".pdf", ".txt", ".md"):
        preferred.extend([p for p in files if p.suffix.lower() == ext])

    chunks: list[str] = []
    for p in preferred[:3]:
        t = _read_text_from_file(p)
        t = (t or "").strip()
        if t:
            chunks.append(t)

    return "\n\n".join(chunks).strip()


def _is_lesson_file(path: pathlib.Path) -> bool:
    ext = path.suffix.lower()
    return ext in {".docx", ".txt", ".md", ".pdf", ".mp4", ".webm", ".png", ".jpg", ".jpeg"}


def _is_module_material(path: pathlib.Path) -> bool:
    ext = path.suffix.lower()
    return ext in {".xlsx", ".xls", ".pptx", ".ppt", ".zip", ".rar", ".7z"}


def _upload_to_s3(*, s3, bucket: str, object_key: str, file_path: pathlib.Path) -> None:
    ct = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    with file_path.open("rb") as f:
        s3.put_object(Bucket=bucket, Key=object_key, Body=f, ContentType=ct)


def _upload_markdown_text(*, s3, bucket: str, object_key: str, text_value: str) -> None:
    data = (text_value or "").encode("utf-8")
    s3.put_object(Bucket=bucket, Key=object_key, Body=data, ContentType="text/markdown; charset=utf-8")


def _cleanup_learning_content(db) -> None:
    db.execute(text("DELETE FROM quiz_attempt_answers"))
    db.execute(text("DELETE FROM quiz_attempts"))
    db.execute(text("DELETE FROM questions"))
    db.execute(text("DELETE FROM submodule_asset_map"))
    db.execute(text("DELETE FROM content_assets"))
    db.execute(text("DELETE FROM submodules"))
    db.execute(text("DELETE FROM module_skill_map"))
    db.execute(text("DELETE FROM modules"))
    db.execute(text("DELETE FROM quizzes"))


def _ensure_quiz_questions(*, db, quiz_id: uuid.UUID, concept_prefix: str, title: str) -> None:
    db.execute(delete(Question).where(Question.quiz_id == quiz_id, Question.concept_tag.like(concept_prefix + "%")))

    # Meaningful questions are generated outside (need access to lesson text). This function is kept
    # for backwards compatibility, but now it only provides a safe fallback.
    qs: list[Question] = [
        Question(
            quiz_id=quiz_id,
            type=QuestionType.single,
            difficulty=1,
            prompt=(
                f"Какой следующий шаг после изучения урока «{title}»?\n"
                "A) Пропустить\nB) Подтвердить прочтение и пройти тест\nC) Завершить модуль\nD) Ничего не делать"
            ),
            correct_answer="B",
            concept_tag=concept_prefix + "fallback_q1",
            variant_group=None,
            explanation=None,
        )
    ]

    for q in qs:
        db.add(q)


def _ensure_final_exam_questions(*, db, quiz_id: uuid.UUID, concept_prefix: str, module_title: str) -> None:
    db.execute(delete(Question).where(Question.quiz_id == quiz_id, Question.concept_tag.like(concept_prefix + "%")))

    qs: list[Question] = [
        Question(
            quiz_id=quiz_id,
            type=QuestionType.single,
            difficulty=2,
            prompt=(
                f"Итоговая аттестация по модулю «{module_title}». Какой принцип делает обучение управляемым?\n"
                "A) Свободное чтение без контроля\nB) Стандарты + обязательная проверка знаний\nC) Только созвоны\nD) Только наставник"
            ),
            correct_answer="B",
            concept_tag=concept_prefix + "q1",
            variant_group=None,
            explanation=None,
        ),
        Question(
            quiz_id=quiz_id,
            type=QuestionType.single,
            difficulty=2,
            prompt=(
                "Когда модуль считается завершенным?\n"
                "A) Когда открыт\nB) Когда прочитаны все уроки\nC) Когда сданы все квизы и итоговый экзамен\nD) Когда скачаны файлы"
            ),
            correct_answer="C",
            concept_tag=concept_prefix + "q2",
            variant_group=None,
            explanation=None,
        ),
        Question(
            quiz_id=quiz_id,
            type=QuestionType.multi,
            difficulty=3,
            prompt=(
                "Что фиксируется системой как прогресс (ответ буквами, пример: ABD)?\n"
                "A) Прочитано\nB) Сдан квиз\nC) Сдан экзамен\nD) Просмотрен файл"
            ),
            correct_answer="A,B,C",
            concept_tag=concept_prefix + "q3",
            variant_group=None,
            explanation=None,
        ),
        Question(
            quiz_id=quiz_id,
            type=QuestionType.single,
            difficulty=2,
            prompt=(
                "Выберите корректный следующий шаг, если квиз не пройден.\n"
                "A) Пропустить\nB) Пересдать квиз\nC) Перейти к экзамену\nD) Завершить модуль"
            ),
            correct_answer="B",
            concept_tag=concept_prefix + "q4",
            variant_group=None,
            explanation=None,
        ),
        Question(
            quiz_id=quiz_id,
            type=QuestionType.single,
            difficulty=2,
            prompt=(
                "Что должно произойти перед открытием экзамена?\n"
                "A) Сданы все квизы уроков\nB) Только прочтено\nC) Только просмотрены материалы\nD) Ничего"
            ),
            correct_answer="A",
            concept_tag=concept_prefix + "q5",
            variant_group=None,
            explanation=None,
        ),
    ]

    for q in qs:
        db.add(q)


def run(*, root: pathlib.Path, do_cleanup: bool, skip_existing: bool) -> None:
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"root folder not found: {root}")

    ensure_bucket_exists()
    s3 = get_s3_client()

    db = SessionLocal()
    try:
        if do_cleanup:
            _cleanup_learning_content(db)
            db.commit()

        module_dirs = sorted([p for p in root.iterdir() if p.is_dir()])
        if not module_dirs:
            raise SystemExit(f"no module directories in {root}")

        for idx, mdir in enumerate(module_dirs, start=1):
            module_title = mdir.name.strip()
            module_slug = _slug(module_title)

            if skip_existing:
                exists = db.scalar(select(Module.id).where(Module.title == module_title))
                if exists is not None:
                    continue

            m = Module(
                title=module_title,
                description=f"Материалы модуля «{module_title}».",
                difficulty=max(1, min(5, idx)),
                category="Обучение",
                is_active=True,
            )
            db.add(m)
            db.flush()

            # Final exam for the module
            final_quiz = Quiz(type=QuizType.final, pass_threshold=70, time_limit=None, attempts_limit=3)
            db.add(final_quiz)
            db.flush()
            m.final_quiz_id = final_quiz.id
            _ensure_final_exam_questions(
                db=db,
                quiz_id=final_quiz.id,
                concept_prefix=f"imp_{module_slug}_final_",
                module_title=module_title,
            )

            # 1) Module-level materials inside _module folder (preferred)
            module_material_dir = mdir / "_module"
            if module_material_dir.exists() and module_material_dir.is_dir():
                for fp in sorted([p for p in module_material_dir.iterdir() if p.is_file() and not p.name.startswith("~$")]):
                    object_key = f"modules/{m.id}/_module/{fp.name}"
                    mime = mimetypes.guess_type(str(fp))[0]

                    asset = db.scalar(select(ContentAsset).where(ContentAsset.object_key == object_key))
                    if asset is None:
                        asset = ContentAsset(
                            bucket=settings.s3_bucket,
                            object_key=object_key,
                            original_filename=fp.name,
                            mime_type=mime,
                            size_bytes=int(fp.stat().st_size) if fp.exists() else None,
                            checksum_sha256=None,
                            created_by=None,
                        )
                        db.add(asset)
                        db.flush()

                    _upload_to_s3(s3=s3, bucket=settings.s3_bucket, object_key=object_key, file_path=fp)

            # 2) Lessons as subfolders (robust mode)
            lesson_dirs = sorted([
                p for p in mdir.iterdir()
                if p.is_dir() and p.name not in {"_module", ".git", "__pycache__"}
            ])

            used_orders: set[int] = set()
            if lesson_dirs:
                for fallback_order, ldir in enumerate(lesson_dirs, start=1):
                    order = _parse_order(ldir.name, fallback_order)
                    while order in used_orders:
                        order += 1
                    used_orders.add(order)

                    lesson_files = sorted([p for p in ldir.rglob("*") if p.is_file() and not p.name.startswith("~$")])
                    if not lesson_files:
                        continue

                    title = _guess_title_from_filename(ldir.name)
                    theory = _extract_theory_from_lesson_files(lesson_files)

                    qz = Quiz(type=QuizType.submodule, pass_threshold=70, time_limit=None, attempts_limit=3)
                    db.add(qz)
                    db.flush()

                    content_key = f"modules/{m.id}/{order:02d}/lesson.md"
                    try:
                        _upload_markdown_text(s3=s3, bucket=settings.s3_bucket, object_key=content_key, text_value=(theory or ""))
                    except Exception:
                        content_key = None

                    sub = Submodule(
                        module_id=m.id,
                        title=title,
                        content=theory or "",
                        content_object_key=content_key,
                        order=order,
                        quiz_id=qz.id,
                    )
                    db.add(sub)
                    db.flush()

                    concept_prefix = f"imp_{module_slug}_s{order}_"
                    facts = _extract_facts(theory)
                    rng = random.Random(f"{module_slug}:{order}")

                    generated: list[_MCQ] = []
                    s1 = _make_single_from_facts(title=title, facts=facts, rng=rng)
                    if s1:
                        generated.append(s1)
                    s2 = _make_single_from_facts(title=title, facts=facts, rng=rng)
                    if s2:
                        generated.append(s2)
                    m1 = _make_multi_from_facts(title=title, facts=facts, rng=rng)
                    if m1:
                        generated.append(m1)

                    if len(generated) < 2:
                        _ensure_quiz_questions(db=db, quiz_id=qz.id, concept_prefix=concept_prefix, title=title)
                    else:
                        for qi, mcq in enumerate(generated, start=1):
                            db.add(
                                Question(
                                    quiz_id=qz.id,
                                    type=mcq.qtype,
                                    difficulty=2 if mcq.qtype == QuestionType.multi else 1,
                                    prompt=mcq.prompt,
                                    correct_answer=mcq.correct_answer,
                                    explanation=None,
                                    concept_tag=f"{concept_prefix}q{qi}",
                                    variant_group=None,
                                )
                            )

                    # Upload and map ALL lesson files
                    per_asset_order = 1
                    for fp in lesson_files:
                        if not _is_lesson_file(fp) and not _is_module_material(fp):
                            continue
                        object_key = f"modules/{m.id}/{order:02d}/{fp.name}"
                        mime = mimetypes.guess_type(str(fp))[0]

                        asset = db.scalar(select(ContentAsset).where(ContentAsset.object_key == object_key))
                        if asset is None:
                            asset = ContentAsset(
                                bucket=settings.s3_bucket,
                                object_key=object_key,
                                original_filename=fp.name,
                                mime_type=mime,
                                size_bytes=int(fp.stat().st_size) if fp.exists() else None,
                                checksum_sha256=None,
                                created_by=None,
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
                            db.add(SubmoduleAssetMap(submodule_id=sub.id, asset_id=asset.id, order=per_asset_order))
                            per_asset_order += 1

                        _upload_to_s3(s3=s3, bucket=settings.s3_bucket, object_key=object_key, file_path=fp)

            # 3) Backward-compatible flat file mode for lessons/materials
            files = sorted([p for p in mdir.iterdir() if p.is_file()])
            order = 1
            for fp in files:
                if fp.name.startswith("~$"):
                    continue

                # If we already imported folder-based lessons, skip turning root files into lessons.
                if lesson_dirs:
                    # Still allow root-level module materials (e.g., xlsx/pptx) to be uploaded
                    if not _is_lesson_file(fp):
                        object_key = f"modules/{m.id}/_module/{fp.name}"
                        mime = mimetypes.guess_type(str(fp))[0]

                        asset = db.scalar(select(ContentAsset).where(ContentAsset.object_key == object_key))
                        if asset is None:
                            asset = ContentAsset(
                                bucket=settings.s3_bucket,
                                object_key=object_key,
                                original_filename=fp.name,
                                mime_type=mime,
                                size_bytes=int(fp.stat().st_size) if fp.exists() else None,
                                checksum_sha256=None,
                                created_by=None,
                            )
                            db.add(asset)
                            db.flush()
                        _upload_to_s3(s3=s3, bucket=settings.s3_bucket, object_key=object_key, file_path=fp)
                    continue

                # Module-level materials (not lessons)
                if _is_module_material(fp) and not _is_lesson_file(fp):
                    object_key = f"modules/{m.id}/_module/{fp.name}"
                    mime = mimetypes.guess_type(str(fp))[0]

                    asset = db.scalar(select(ContentAsset).where(ContentAsset.object_key == object_key))
                    if asset is None:
                        asset = ContentAsset(
                            bucket=settings.s3_bucket,
                            object_key=object_key,
                            original_filename=fp.name,
                            mime_type=mime,
                            size_bytes=int(fp.stat().st_size) if fp.exists() else None,
                            checksum_sha256=None,
                            created_by=None,
                        )
                        db.add(asset)
                        db.flush()

                    _upload_to_s3(s3=s3, bucket=settings.s3_bucket, object_key=object_key, file_path=fp)
                    continue

                # Skip unknown/binary files from becoming lessons
                if not _is_lesson_file(fp):
                    object_key = f"modules/{m.id}/_module/{fp.name}"
                    mime = mimetypes.guess_type(str(fp))[0]

                    asset = db.scalar(select(ContentAsset).where(ContentAsset.object_key == object_key))
                    if asset is None:
                        asset = ContentAsset(
                            bucket=settings.s3_bucket,
                            object_key=object_key,
                            original_filename=fp.name,
                            mime_type=mime,
                            size_bytes=int(fp.stat().st_size) if fp.exists() else None,
                            checksum_sha256=None,
                            created_by=None,
                        )
                        db.add(asset)
                        db.flush()

                    _upload_to_s3(s3=s3, bucket=settings.s3_bucket, object_key=object_key, file_path=fp)
                    continue

                title = _guess_title_from_filename(fp.name)
                theory = _read_text_from_file(fp)

                qz = Quiz(type=QuizType.submodule, pass_threshold=70, time_limit=None, attempts_limit=3)
                db.add(qz)
                db.flush()

                content_key = f"modules/{m.id}/{order:02d}/lesson.md"
                try:
                    _upload_markdown_text(s3=s3, bucket=settings.s3_bucket, object_key=content_key, text_value=(theory or ""))
                except Exception:
                    content_key = None

                sub = Submodule(
                    module_id=m.id,
                    title=title,
                    content=theory or "",
                    content_object_key=content_key,
                    order=order,
                    quiz_id=qz.id,
                )
                db.add(sub)
                db.flush()

                concept_prefix = f"imp_{module_slug}_s{order}_"
                facts = _extract_facts(theory)
                rng = random.Random(f"{module_slug}:{order}")

                generated: list[_MCQ] = []
                s1 = _make_single_from_facts(title=title, facts=facts, rng=rng)
                if s1:
                    generated.append(s1)
                s2 = _make_single_from_facts(title=title, facts=facts, rng=rng)
                if s2:
                    generated.append(s2)
                m1 = _make_multi_from_facts(title=title, facts=facts, rng=rng)
                if m1:
                    generated.append(m1)

                # If we failed to generate enough meaningful questions, add safe fallback.
                if len(generated) < 2:
                    _ensure_quiz_questions(db=db, quiz_id=qz.id, concept_prefix=concept_prefix, title=title)
                else:
                    for qi, mcq in enumerate(generated, start=1):
                        db.add(
                            Question(
                                quiz_id=qz.id,
                                type=mcq.qtype,
                                difficulty=2 if mcq.qtype == QuestionType.multi else 1,
                                prompt=mcq.prompt,
                                correct_answer=mcq.correct_answer,
                                explanation=None,
                                concept_tag=f"{concept_prefix}q{qi}",
                                variant_group=None,
                            )
                        )

                object_key = f"modules/{m.id}/{order:02d}/{fp.name}"
                mime = mimetypes.guess_type(str(fp))[0]

                asset = db.scalar(select(ContentAsset).where(ContentAsset.object_key == object_key))
                if asset is None:
                    asset = ContentAsset(
                        bucket=settings.s3_bucket,
                        object_key=object_key,
                        original_filename=fp.name,
                        mime_type=mime,
                        size_bytes=int(fp.stat().st_size) if fp.exists() else None,
                        checksum_sha256=None,
                        created_by=None,
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
                    db.add(SubmoduleAssetMap(submodule_id=sub.id, asset_id=asset.id, order=1))

                _upload_to_s3(s3=s3, bucket=settings.s3_bucket, object_key=object_key, file_path=fp)

                order += 1

            db.flush()

        db.commit()
        print(f"OK: imported {len(module_dirs)} modules from {root}")
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default="/app/Модули обучения", help="Path to modules root folder")
    p.add_argument("--cleanup", action="store_true", help="Delete existing modules/quizzes/assets before import")
    p.add_argument("--skip-existing", action="store_true", help="Skip modules with same title already in DB")
    args = p.parse_args()

    run(root=pathlib.Path(args.root), do_cleanup=bool(args.cleanup), skip_existing=bool(args.skip_existing))


if __name__ == "__main__":
    main()
