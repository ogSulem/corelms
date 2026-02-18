from __future__ import annotations

import logging
import mimetypes
import pathlib
import re
import random
import uuid
import zipfile

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from rq import get_current_job

from app.core.config import settings
from app.core.redis_client import get_redis
from app.models.asset import ContentAsset
from app.models.module import Module, Submodule
from app.models.quiz import Question, QuestionType, Quiz, QuizType
from app.models.submodule_asset import SubmoduleAssetMap
from app.services.llm_handler import choose_llm_provider_order_fast, generate_quiz_questions_ai
from app.services.quiz_generation import generate_quiz_questions_heuristic
from app.services.storage import ensure_bucket_exists, get_s3_client


log = logging.getLogger(__name__)


def _set_job_detail(detail: str) -> None:
    try:
        job = get_current_job()
    except Exception:
        job = None
    if job is None:
        return
    try:
        meta = dict(job.meta or {})
        meta["detail"] = str(detail)
        job.meta = meta
        job.save_meta()
    except Exception:
        return


def _track_uploaded_key(object_key: str) -> None:
    try:
        job = get_current_job()
    except Exception:
        job = None
    if job is None:
        return
    try:
        meta = dict(job.meta or {})
        keys = list(meta.get("uploaded_keys") or [])
        k = str(object_key or "").strip()
        if k and k not in keys:
            keys.append(k)
            # Keep last N keys to avoid unbounded growth.
            meta["uploaded_keys"] = keys[-2000:]
            job.meta = meta
            job.save_meta()
    except Exception:
        return


def _guess_title(name: str) -> str:
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


def _is_lesson_asset(path: pathlib.Path) -> bool:
    return path.suffix.lower() in {".docx", ".txt", ".md", ".pdf", ".mp4", ".webm", ".png", ".jpg", ".jpeg"}


def _is_module_material(path: pathlib.Path) -> bool:
    return path.suffix.lower() in {".xlsx", ".xls", ".pptx", ".ppt", ".zip", ".rar", ".7z"}


def _clean_line(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).strip()


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


def _read_text(path: pathlib.Path) -> str:
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


def _theory_from_files(files: list[pathlib.Path]) -> str:
    preferred: list[pathlib.Path] = []
    for ext in (".docx", ".pdf", ".txt", ".md"):
        preferred.extend([p for p in files if p.suffix.lower() == ext])

    chunks: list[str] = []
    for p in preferred[:3]:
        t = _read_text(p)
        if t:
            chunks.append(t)
    return "\n\n".join(chunks).strip()


def _is_theory_file(p: pathlib.Path) -> bool:
    return p.suffix.lower() in {".docx", ".pdf", ".txt", ".md"}


def _upload_file(*, s3, object_key: str, file_path: pathlib.Path) -> tuple[str | None, int | None]:
    ct = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    with file_path.open("rb") as f:
        s3.put_object(Bucket=settings.s3_bucket, Key=object_key, Body=f, ContentType=ct)
    _track_uploaded_key(object_key)
    size = int(file_path.stat().st_size) if file_path.exists() else None
    return ct, size


def _upload_markdown_text(*, s3, object_key: str, text_value: str) -> None:
    data = (text_value or "").encode("utf-8")
    s3.put_object(Bucket=settings.s3_bucket, Key=object_key, Body=data, ContentType="text/markdown; charset=utf-8")
    _track_uploaded_key(object_key)


def _lesson_markdown_fallback(*, module_title: str, lesson_title: str, files: list[pathlib.Path]) -> str:
    assets = [p for p in files if p.is_file() and not _is_theory_file(p)]
    if not assets:
        return f"# {lesson_title}\n\nМатериалы модуля «{module_title}».".strip()
    lines: list[str] = [f"# {lesson_title}", "", f"Материалы модуля «{module_title}»:", ""]
    for p in sorted(assets, key=lambda x: x.name.lower()):
        lines.append(f"- {p.name}")
    return "\n".join(lines).strip()


def import_module_from_dir(
    *,
    db: Session,
    module_dir: pathlib.Path,
    title_override: str | None = None,
    report_out: dict | None = None,
    generate_questions: bool = True,
) -> uuid.UUID:
    ensure_bucket_exists()
    s3 = get_s3_client()

    module_title = (title_override or module_dir.name).strip() or "Модуль"

    # Commercial-grade behavior: do not allow silent duplicates.
    existing = db.scalar(select(Module).where(func.lower(Module.title) == func.lower(module_title)))
    if existing is not None:
        raise ValueError(f"module title already exists: {module_title}")

    report: dict[str, object] | None = None
    if report_out is not None:
        report = report_out  # mutate caller-owned dict
        report.setdefault("module_title", module_title)
        report.setdefault("submodules", 0)
        report.setdefault("module_assets", 0)
        report.setdefault("lesson_assets", 0)
        report.setdefault("questions_total", 0)
        report.setdefault("questions_ai", 0)
        report.setdefault("questions_heur", 0)
        report.setdefault("questions_fallback", 0)
        report.setdefault("needs_regen", 0)
        report.setdefault("ollama_enabled", bool(settings.ollama_enabled))
        report.setdefault("ollama_used", False)

    # Product rule: final exam questions are generated at runtime on /quizzes/{id}/start.
    # We still keep a stable final_quiz_id so the UI/routes can reference the final exam.
    final_quiz = Quiz(type=QuizType.final, pass_threshold=70, time_limit=None, attempts_limit=3)
    db.add(final_quiz)
    db.flush()

    m = Module(
        title=module_title,
        description=f"Материалы модуля «{module_title}».",
        difficulty=1,
        category="Обучение",
        # Product rule: imported module is hidden from learners until quizzes are fully generated.
        # We will auto-activate at the end if import didn't flag needs_regen questions.
        is_active=False,
        final_quiz_id=final_quiz.id,
    )
    db.add(m)
    db.flush()

    log.info("module_importer: created module id=%s title=%s", str(m.id), module_title)
    print(f"module_importer: module created id={m.id} title={module_title}", flush=True)

    # Normalize module_dir if the ZIP has an extra nesting level.
    for _ in range(2):
        lesson_dirs_probe = [d for d in module_dir.iterdir() if d.is_dir() and d.name not in {"_module", "__MACOSX"}]
        if lesson_dirs_probe:
            break
        nested = [d for d in module_dir.iterdir() if d.is_dir() and d.name not in {"__MACOSX"}]
        if len(nested) == 1:
            module_dir = nested[0]
            continue
        break

    module_material_dir = module_dir / "_module"
    if module_material_dir.exists() and module_material_dir.is_dir():
        for fp in sorted([p for p in module_material_dir.iterdir() if p.is_file() and not p.name.startswith("~$")]):
            _set_job_detail(f"material: {fp.name}")
            object_key = f"modules/{m.id}/_module/{fp.name}"
            mime, size = _upload_file(s3=s3, object_key=object_key, file_path=fp)

            asset = ContentAsset(
                bucket=settings.s3_bucket,
                object_key=object_key,
                original_filename=fp.name,
                mime_type=mime,
                size_bytes=size,
                checksum_sha256=None,
                created_by=None,
            )
            db.add(asset)
            db.flush()

            if report is not None:
                report["module_assets"] = int(report.get("module_assets") or 0) + 1

    lesson_candidates = [d for d in module_dir.iterdir() if d.is_dir() and d.name not in {"_module", "__MACOSX"}]
    if not lesson_candidates:
        for d in sorted([p for p in module_dir.iterdir() if p.is_dir() and p.name not in {"_module", "__MACOSX"}]):
            inner = [x for x in d.iterdir() if x.is_dir() and x.name not in {"_module", "__MACOSX"}]
            if inner:
                module_dir = d
                lesson_candidates = inner
                break

    lesson_dirs = sorted(lesson_candidates, key=lambda x: _parse_order(x.name, 999))

    root_as_lesson = False
    if not lesson_dirs:
        # Some ZIPs come as a flat folder: theory files are placed directly in module root.
        # In this case we import the module root as a single lesson.
        root_as_lesson = True
        lesson_dirs = [module_dir]

    if root_as_lesson:
        root_files = sorted([p for p in module_dir.iterdir() if p.is_file() and not p.name.startswith("~$")])
        theory_files = [p for p in root_files if _is_theory_file(p)]
        if len(theory_files) > 1:
            theory_files = sorted(theory_files, key=lambda x: _parse_order(x.name, 999))
            lesson_specs: list[tuple[int, str, list[pathlib.Path]]] = []
            for i, tf in enumerate(theory_files, start=1):
                lesson_specs.append((i, _guess_title(tf.stem), [tf]))
            extra_assets = [p for p in root_files if p not in set(theory_files)]
        else:
            # Single-file (or no-file) flat module.
            lesson_specs = [(1, module_title, root_files)]
            extra_assets = []
    else:
        lesson_specs = []
        extra_assets = []
        for i, ld in enumerate(lesson_dirs, start=1):
            lesson_specs.append((_parse_order(ld.name, i), _guess_title(ld.name), sorted([p for p in ld.iterdir() if p.is_file() and not p.name.startswith("~$")])) )

    total_lessons = len(lesson_specs)

    for i, (order, title, files) in enumerate(lesson_specs, start=1):
        _set_job_detail(f"lesson {i}/{total_lessons}: {title}")
        theory = _theory_from_files(files)

        if not (theory or "").strip():
            theory = _lesson_markdown_fallback(module_title=module_title, lesson_title=title, files=files)

        content_key = f"modules/{m.id}/{order:02d}/theory.md"
        _upload_markdown_text(s3=s3, object_key=content_key, text_value=theory)

        qz = Quiz(type=QuizType.submodule, pass_threshold=70, time_limit=None, attempts_limit=None)
        db.add(qz)
        db.flush()

        s = Submodule(
            module_id=m.id,
            title=title,
            content=theory,
            order=order,
            quiz_id=qz.id,
        )
        db.add(s)
        db.flush()

        if report is not None:
            report["submodules"] = int(report.get("submodules") or 0) + 1

        # Phase 1: if generate_questions=False (default for fast ingest), create placeholders.
        # Phase 2: if generate_questions=True (background regen), call AI/Heuristic.
        if generate_questions:
            qs = []
            if settings.ollama_enabled or settings.hf_router_enabled or settings.openrouter_enabled:
                provider_order = choose_llm_provider_order_fast(ttl_seconds=300, use_cache=False)
                qs = generate_quiz_questions_ai(
                    title=title,
                    text=theory or "",
                    n_questions=5,
                    min_questions=5,
                    retries=5,
                    backoff_seconds=0.9,
                    provider_order=provider_order,
                )
                if qs:
                    for qi, q in enumerate(qs, start=1):
                        raw_type = str(getattr(q, "qtype", None) or getattr(q, "type", "") or "").strip().lower()
                        qtype = "multi" if raw_type == "multi" else "single"
                        db.add(
                            Question(
                                quiz_id=qz.id,
                                type=QuestionType.single if qtype == "single" else QuestionType.multi,
                                difficulty=2 if qtype == "multi" else 1,
                                prompt=str(getattr(q, "prompt", "") or ""),
                                correct_answer=str(getattr(q, "correct_answer", "") or ""),
                                explanation=(getattr(q, "explanation", None) if getattr(q, "explanation", None) else None),
                                concept_tag=f"ai:{m.id}:{order}:{qi}",
                                variant_group=None,
                            )
                        )
                    if report is not None:
                        report["questions_ai"] = int(report.get("questions_ai") or 0) + len(qs)
                        report["questions_total"] = int(report.get("questions_total") or 0) + len(qs)

            if not qs:
                # Fallback to Heuristic
                generated = generate_quiz_questions_heuristic(
                    seed=f"{m.id}:{order}",
                    title=title,
                    theory_text=theory or "",
                    target=5,
                )
                if generated:
                    for qi, mcq in enumerate(generated, start=1):
                        db.add(
                            Question(
                                quiz_id=qz.id,
                                type=QuestionType.single if mcq.qtype == "single" else QuestionType.multi,
                                difficulty=2 if mcq.qtype == "multi" else 1,
                                prompt=mcq.prompt,
                                correct_answer=mcq.correct_answer,
                                explanation=None,
                                concept_tag=f"needs_regen:heur:{m.id}:{order}:{qi}",
                                variant_group=None,
                            )
                        )
                    if report is not None:
                        report["needs_regen"] = int(report.get("needs_regen") or 0) + 1
                        report["questions_heur"] = int(report.get("questions_heur") or 0) + len(generated)
                        report["questions_total"] = int(report.get("questions_total") or 0) + len(generated)
        else:
            # Quick placeholder creation for two-phase import.
            db.add(
                Question(
                    quiz_id=qz.id,
                    type=QuestionType.single,
                    difficulty=1,
                    prompt=(
                        f"По уроку «{title}» выберите верный вариант.\n"
                        "A) Подтвердить прочтение и пройти квиз\nB) Пропустить урок\nC) Завершить модуль без проверки\nD) Ничего не делать"
                    ),
                    correct_answer="A",
                    explanation=None,
                    concept_tag=f"needs_regen:import:{m.id}:{order}:1",
                    variant_group=None,
                )
            )
            if report is not None:
                report["needs_regen"] = int(report.get("needs_regen") or 0) + 1
                report["questions_total"] = int(report.get("questions_total") or 0) + 1

        per_asset_order = 1
        # If this module is flat (no lesson folders), attach non-theory assets to the first lesson.
        if root_as_lesson and i == 1 and extra_assets:
            files = list(files) + list(extra_assets)
        for fp in files:
            if not _is_lesson_asset(fp) and not _is_module_material(fp):
                continue

            _set_job_detail(f"asset: {fp.name}")

            if _is_module_material(fp) and not _is_lesson_asset(fp):
                object_key = f"modules/{m.id}/_module/{fp.name}"
                mime, size = _upload_file(s3=s3, object_key=object_key, file_path=fp)

                asset = db.scalar(select(ContentAsset).where(ContentAsset.object_key == object_key))
                if asset is None:
                    asset = ContentAsset(
                        bucket=settings.s3_bucket,
                        object_key=object_key,
                        original_filename=fp.name,
                        mime_type=mime,
                        size_bytes=size,
                        checksum_sha256=None,
                        created_by=None,
                    )
                    db.add(asset)
                    db.flush()

                if report is not None:
                    report["module_assets"] = int(report.get("module_assets") or 0) + 1
                continue

            object_key = f"modules/{m.id}/{order:02d}/{fp.name}"
            mime, size = _upload_file(s3=s3, object_key=object_key, file_path=fp)

            asset = db.scalar(select(ContentAsset).where(ContentAsset.object_key == object_key))
            if asset is None:
                asset = ContentAsset(
                    bucket=settings.s3_bucket,
                    object_key=object_key,
                    original_filename=fp.name,
                    mime_type=mime,
                    size_bytes=size,
                    checksum_sha256=None,
                    created_by=None,
                )
                db.add(asset)
                db.flush()

            db.add(
                SubmoduleAssetMap(
                    submodule_id=s.id,
                    asset_id=asset.id,
                    order=per_asset_order,
                )
            )
            per_asset_order += 1

            if report is not None:
                report["lesson_assets"] = int(report.get("lesson_assets") or 0) + 1

    db.commit()
    return m.id
