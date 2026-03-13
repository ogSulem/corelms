from __future__ import annotations

import logging
import mimetypes
import pathlib
import re
import random
import time
import uuid
import zipfile
import unicodedata

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
from app.services.quiz_text import is_useful_quiz_text
from app.services.storage import ensure_bucket_exists, get_s3_client, upload_fileobj_with_retry


log = logging.getLogger(__name__)


def _slugify_s3_segment(v: str) -> str:
    s = str(v or "")
    try:
        s = unicodedata.normalize("NFKC", s)
    except Exception:
        pass
    s = s.strip()
    try:
        bad = ("Ã" in s) or ("Ð" in s) or ("Ñ" in s)
        if bad:
            try:
                fixed = s.encode("latin-1", errors="strict").decode("utf-8", errors="strict")
                if fixed and fixed != s:
                    s = fixed
            except Exception:
                pass
    except Exception:
        pass

    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s).strip()
    if s.endswith(".zip"):
        s = s[: -len(".zip")]
    s = re.sub(r"[^0-9a-zа-яё\-_. ]+", "-", s, flags=re.IGNORECASE)
    s = s.replace(" ", "-")
    s = re.sub(r"-+", "-", s).strip("-._")
    return (s[:80] or "module")


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
        log.debug("module_importer: failed to save job meta detail", exc_info=True)
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
        log.debug("module_importer: failed to save job meta uploaded_keys", exc_info=True)
        return


def _guess_title(name: str) -> str:
    s = re.sub(r"^\s*\d+\s*[.)_-]*\s*", "", name)
    s = re.sub(r"\.[a-zA-Z0-9]+$", "", s)
    return s.strip() or name


def _outline_segments(parts: list[str]) -> list[str]:
    # Keep folder navigation stable by applying the same title normalization
    # that we apply to lesson/folder titles.
    out: list[str] = []
    for p in parts or []:
        seg = _guess_title(str(p or "").strip())
        seg = seg.strip().strip("/")
        if seg:
            out.append(seg)
    return out


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
    # Legacy compatibility: kept for filtering theory vs. assets.
    # The importer is designed to accept arbitrary file types as assets.
    return True


def _is_module_material(path: pathlib.Path) -> bool:
    return path.suffix.lower() in {".xlsx", ".xls", ".pptx", ".ppt", ".zip", ".rar", ".7z"}


def _should_ignore_file(p: pathlib.Path) -> bool:
    n = str(p.name or "").strip().lower()
    if not n:
        return True
    if p.name.startswith("._"):
        return True
    try:
        parts = {x for x in p.parts}
        if "__MACOSX" in parts:
            return True
    except Exception:
        pass

    return False


def _asset_sort_key(*, fp: pathlib.Path, lesson_root: pathlib.Path) -> tuple[int, str]:
    """Natural ordering for lesson assets (as they appear in ZIP).
    """
    try:
        rel = fp.relative_to(lesson_root)
        rel_name = str(rel.as_posix())
    except Exception:
        rel_name = str(fp.name or "")

    # Keep root-level files before deeply nested ones, then alphabetical by name
    depth = rel_name.count("/")
    return (depth, rel_name.casefold())


def _list_files_recursive(root: pathlib.Path) -> list[pathlib.Path]:
    try:
        return sorted([p for p in root.rglob("*") if p.is_file() and not _should_ignore_file(p)])
    except Exception:
        return []


def _has_any_lesson_content(root: pathlib.Path) -> bool:
    for fp in _list_files_recursive(root):
        if _is_lesson_asset(fp) or _is_module_material(fp) or _is_theory_file(fp):
            return True
    return False


def _collect_leaf_lesson_dirs(root: pathlib.Path) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    try:
        direct_files = [p for p in root.iterdir() if p.is_file() and not _should_ignore_file(p)]
        direct_dirs = [p for p in root.iterdir() if p.is_dir() and p.name not in {"_module", "__MACOSX"}]
    except Exception:
        return out

    if direct_files:
        return [root]

    for d in sorted(direct_dirs, key=lambda x: _parse_order(x.name, 999)):
        if not _has_any_lesson_content(d):
            continue
        out.extend(_collect_leaf_lesson_dirs(d))
    return out


def _clean_line(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).strip()


def _normalize_text_to_markdown(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return ""

    raw = raw.replace("\u00a0", " ")
    raw = re.sub(r"[ \t]+", " ", raw)

    src_lines = raw.split("\n")
    lines: list[str] = []
    prev_empty = True
    for ln in src_lines:
        s = ln.strip()
        if not s:
            if not prev_empty:
                lines.append("")
            prev_empty = True
            continue

        if s.startswith("•"):
            s = "- " + s[1:].strip()
        s = re.sub(r"^\*\s+", "- ", s)

        lines.append(s)
        prev_empty = False

    merged: list[str] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        if cur == "":
            if merged and merged[-1] != "":
                merged.append("")
            i += 1
            continue

        def is_list_item(x: str) -> bool:
            return bool(
                re.match(r"^(?:-\s+|\d{1,3}[.)]\s+)", x)
                or x.startswith("•")
            )

        if merged and merged[-1] != "":
            prev = merged[-1]
            if prev.endswith("-") and not prev.endswith(" -"):
                merged[-1] = prev[:-1] + cur
                i += 1
                continue

            prev_is_list = is_list_item(prev)
            cur_is_list = is_list_item(cur)
            if (not prev_is_list) and (not cur_is_list):
                prev_end = prev[-1] if prev else ""
                cur_start = cur[0] if cur else ""
                should_wrap = prev_end not in ".?!:;" and cur_start.islower()
                if should_wrap:
                    merged[-1] = prev + " " + cur
                    i += 1
                    continue

        merged.append(cur)
        i += 1

    out = "\n".join(merged)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def _docx_to_text(path: pathlib.Path) -> str:
    try:
        with zipfile.ZipFile(path, "r") as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<[^>]+>", "", xml)
        xml = re.sub(r"\n{3,}", "\n\n", xml)
        return _normalize_text_to_markdown(xml)
    except Exception:
        return ""


def _pdf_to_text(path: pathlib.Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages[:30]:
            t = page.extract_text() or ""
            t = _normalize_text_to_markdown(t)
            if t:
                parts.append(t)
        return "\n\n".join(parts).strip()
    except Exception:
        return ""


def _read_text(path: pathlib.Path) -> str:
    ext = path.suffix.lower()
    if ext in {".txt", ".md"}:
        try:
            txt = path.read_text(encoding="utf-8", errors="ignore")
            if ext == ".md":
                return txt.strip()
            return _normalize_text_to_markdown(txt)
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


def _is_previewable_lesson_asset(p: pathlib.Path) -> bool:
    ext = str(p.suffix or "").lower()
    if ext.startswith("."):
        ext = ext[1:]

    # "Previewable" means: can be meaningfully shown on the lesson page.
    # - Inline: video/audio/images/pdf/text
    # - Download-only but still lesson-worthy: office/docs/spreadsheets/presentations
    return ext in {
        # text
        "txt",
        "md",
        "json",
        # pdf
        "pdf",
        # images
        "png",
        "jpg",
        "jpeg",
        "webp",
        "gif",
        "svg",
        # video
        "mp4",
        "webm",
        "mov",
        "mkv",
        # audio
        "mp3",
        "wav",
        "ogg",
        "m4a",
        # office
        "doc",
        "docx",
        "ppt",
        "pptx",
        "xls",
        "xlsx",
        "csv",
    }


def _upload_file(*, s3, object_key: str, file_path: pathlib.Path) -> tuple[str | None, int | None]:
    ct = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    size = int(file_path.stat().st_size) if file_path.exists() else None
    with file_path.open("rb") as f:
        upload_fileobj_with_retry(
            s3=s3,
            object_key=object_key,
            fileobj=f,
            content_type=ct,
            size_bytes=size,
        )
    _track_uploaded_key(object_key)
    return ct, size


def _upload_markdown_text(*, s3, object_key: str, text_value: str) -> None:
    data = (text_value or "").encode("utf-8")
    _s3_put_object_with_retry(s3=s3, object_key=object_key, body=data, content_type="text/markdown; charset=utf-8")
    _track_uploaded_key(object_key)


def _s3_put_object_with_retry(*, s3, object_key: str, body: object, content_type: str) -> None:
    tries = 4
    base = 0.6
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            s3.put_object(Bucket=settings.s3_bucket, Key=object_key, Body=body, ContentType=content_type)
            return
        except Exception as e:
            last = e
            if attempt >= tries:
                raise
            try:
                time.sleep(base * (2 ** (attempt - 1)) + random.random() * 0.25)
            except Exception:
                pass
    if last is not None:
        raise last


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
    module_id_override: str | None = None,
) -> uuid.UUID:
    ensure_bucket_exists()
    s3 = get_s3_client()

    module_title = (title_override or module_dir.name).strip() or "Модуль"

    m: Module | None = None
    if str(module_id_override or "").strip():
        try:
            mid = uuid.UUID(str(module_id_override))
        except Exception as e:
            raise ValueError(f"invalid module_id_override: {module_id_override}") from e
        m = db.scalar(select(Module).where(Module.id == mid))
        if m is None:
            raise ValueError(f"module_id_override not found: {module_id_override}")
        # Update stub metadata to match inferred title.
        m.title = module_title
        m.description = f"Материалы модуля «{module_title}»."
        m.is_active = False
        db.add(m)
        db.flush()
    else:
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
        report.setdefault("ai_enabled", bool(settings.openrouter_enabled))
        report.setdefault("ai_used", False)

    if m is None:
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

    pfx = str(getattr(m, "storage_prefix", "") or "").strip()
    if not pfx:
        safe = _slugify_s3_segment(module_title)
        pfx = f"modules/{safe}__{str(m.id)}/"
        try:
            m.storage_prefix = pfx
            db.add(m)
            db.flush()
        except Exception:
            pfx = f"modules/{str(m.id)}/"

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
    module_material_viewable: list[pathlib.Path] = []
    if module_material_dir.exists() and module_material_dir.is_dir():
        for fp in _list_files_recursive(module_material_dir):
            try:
                rel = fp.relative_to(module_material_dir)
                rel_name = str(rel.as_posix())
            except Exception:
                rel_name = fp.name

            _set_job_detail(f"material: {rel_name}")
            object_key = f"{pfx}_module/{rel_name}"
            mime, size = _upload_file(s3=s3, object_key=object_key, file_path=fp)

            asset = db.scalar(select(ContentAsset).where(ContentAsset.object_key == object_key))
            if asset is None:
                asset = ContentAsset(
                    bucket=settings.s3_bucket,
                    object_key=object_key,
                    original_filename=rel_name,
                    mime_type=mime,
                    size_bytes=size,
                    checksum_sha256=None,
                    created_by=None,
                )
                db.add(asset)
                db.flush()

            if _is_previewable_lesson_asset(fp):
                module_material_viewable.append(fp)

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

    try:
        module_dir_abs = module_dir.resolve()
    except Exception:
        module_dir_abs = module_dir

    root_as_lesson = False
    if not lesson_dirs:
        # Some ZIPs come as a flat folder: theory files are placed directly in module root.
        # In this case we import the module root as a single lesson.
        root_as_lesson = True
        lesson_dirs = [module_dir]

    if root_as_lesson:
        root_files = sorted([p for p in module_dir.iterdir() if p.is_file() and not _should_ignore_file(p)])
        # Ideal behavior for flat modules: if there are multiple files directly in module root,
        # import each file as a separate material lesson (no quiz).
        if len(root_files) > 1:
            lesson_specs = []
            extra_assets = []
            for i, fp in enumerate(sorted(root_files, key=lambda x: (_parse_order(x.name, 999), x.name.lower())), start=1):
                lesson_specs.append((i, _guess_title(fp.stem), [fp]))
        else:
            # Single-file (or no-file) flat module.
            lesson_specs = [(1, module_title, root_files)]
            extra_assets = []
    else:
        # Mixed mode: module has lesson folders AND files in module root.
        # Treat root-level files as their own lesson(s) instead of dropping them.
        root_files = sorted([p for p in module_dir.iterdir() if p.is_file() and not _should_ignore_file(p)])
        root_theory_files = [p for p in root_files if _is_theory_file(p)]

        lesson_specs = []
        extra_assets = []
        nested_order = 0

        if root_files:
            if len(root_theory_files) > 1:
                root_theory_files = sorted(root_theory_files, key=lambda x: _parse_order(x.name, 999))
                for tf in root_theory_files:
                    lesson_specs.append((_parse_order(tf.name, 999), _guess_title(tf.stem), [tf], module_dir))
                root_extra_assets = [p for p in root_files if p not in set(root_theory_files)]
                if root_extra_assets:
                    base = max([_parse_order(tf.name, 999) for tf in (root_theory_files or [])] + [0])
                    for j, fp in enumerate(
                        sorted(root_extra_assets, key=lambda x: (_parse_order(x.name, 999), x.name.lower())),
                        start=1,
                    ):
                        lesson_specs.append((base + j, _guess_title(fp.stem), [fp], module_dir))
            else:
                title0 = _guess_title(module_dir.name) or module_title
                lesson_specs.append((_parse_order(module_dir.name, 0), title0, root_files, module_dir))

        for i, ld in enumerate(lesson_dirs, start=1):
            # Product rule:
            # - Any directory under module root is imported as a SINGLE folder lesson (catalog).
            # - Files inside are assets of that folder (including nested folders), not separate submodules.
            if ld.is_dir():
                files2 = _list_files_recursive(ld)
                files2 = [p for p in files2 if not _should_ignore_file(p)]
                if not files2:
                    continue

                lesson_specs.append((_parse_order(ld.name, i), _guess_title(ld.name), files2, ld, None, True))
                continue

            direct_files = []

            # No direct files and no subdirs: ignore.
            files2 = _list_files_recursive(ld)
            files2 = [p for p in files2 if not _should_ignore_file(p)]
            if files2:
                lesson_specs.append((_parse_order(ld.name, i), _guess_title(ld.name), files2, ld))

    # Add viewable module materials as separate material lessons (no quiz).
    if module_material_viewable:
        base = max([int(x[0]) for x in (lesson_specs or [(0, "", [])])] + [0])
        for j, fp in enumerate(
            sorted(module_material_viewable, key=lambda x: (_parse_order(x.name, 999), x.name.lower())),
            start=1,
        ):
            lesson_specs.append((base + j, _guess_title(fp.stem), [fp], module_material_dir))

    total_lessons = len(lesson_specs)

    # lesson_specs item formats:
    # - (order, title, files)
    # - (order, title, files, lesson_root)
    # - (order, title, files, lesson_root, outline_path_override)
    # - (order, title, files, lesson_root, outline_path_override, is_folder)
    normalized_specs: list[tuple[int, str, list[pathlib.Path], pathlib.Path, str | None, bool]] = []
    for spec in lesson_specs:
        if len(spec) == 3:
            o, t, f = spec  # type: ignore[misc]
            normalized_specs.append((int(o), str(t), list(f), module_dir, None, False))
        elif len(spec) == 4:
            o, t, f, root = spec  # type: ignore[misc]
            normalized_specs.append((int(o), str(t), list(f), pathlib.Path(root), None, False))
        elif len(spec) == 5:
            o, t, f, root, outline_override = spec  # type: ignore[misc]
            normalized_specs.append((int(o), str(t), list(f), pathlib.Path(root), str(outline_override) if outline_override else None, False))
        else:
            o, t, f, root, outline_override, is_folder = spec  # type: ignore[misc]
            normalized_specs.append(
                (int(o), str(t), list(f), pathlib.Path(root), str(outline_override) if outline_override else None, bool(is_folder))
            )

    normalized_specs.sort(key=lambda x: (x[0], x[1].lower()))
    renum: list[tuple[int, str, list[pathlib.Path], pathlib.Path, str | None, bool]] = []
    for idx, (_, t, f, root, outline_override, is_folder) in enumerate(normalized_specs, start=1):
        renum.append((idx, t, f, root, outline_override, is_folder))

    # If this module is flat (no lesson folders) and has multiple files in root,
    # all lessons are treated as materials-only (requires_quiz=false).
    flat_multi_root_files = bool(root_as_lesson and len([p for p in module_dir.iterdir() if p.is_file() and not _should_ignore_file(p)]) > 1)
    material_roots = {module_material_dir.resolve()} if module_material_dir.exists() else set()
    for i, (order, title, files, lesson_root, outline_override, is_folder) in enumerate(renum, start=1):
        _set_job_detail(f"lesson {i}/{total_lessons}: {title}")

        outline_path: str | None = outline_override
        if outline_path is None:
            try:
                try:
                    lesson_root_abs = lesson_root.resolve()
                except Exception:
                    lesson_root_abs = lesson_root

                rel = lesson_root_abs.relative_to(module_dir_abs)
                parts = [p for p in rel.parts if p and p not in {"_module", "__MACOSX"}]
                if len(parts) > 1:
                    outline_path = "/".join(_outline_segments([str(x) for x in parts[:-1]]))
            except Exception:
                outline_path = None

        extracted_theory = _theory_from_files(files)
        extracted_theory_clean = str(extracted_theory or "").strip()
        extracted_ok = bool(is_useful_quiz_text(extracted_theory_clean))

        non_theory_files = [p for p in files if p.is_file() and not _is_theory_file(p)]
        has_previewable_assets = any(_is_previewable_lesson_asset(p) for p in non_theory_files)

        # Product rule:
        # - Generate quizzes for lessons where we can extract meaningful text (PDF/DOCX/TXT/MD).
        # - Otherwise treat as materials-only (file lesson), even if it's a non-previewable binary.
        # This avoids generating quizzes from a fallback "file list" markdown.
        materials_only = not extracted_ok
        try:
            if flat_multi_root_files:
                # Flat modules are usually materials-only, but if we can extract real text,
                # treat the lesson as quiz-capable even in flat structure.
                materials_only = (not extracted_ok)
            elif lesson_root and lesson_root.exists() and lesson_root.is_dir() and lesson_root.resolve() in material_roots:
                materials_only = True
            elif is_folder:
                extracted_ok = False
                materials_only = True
                outline_path = None
            elif outline_path:
                # Product rule for nested outline folders: view-only content. No quizzes/regens.
                extracted_ok = False
                materials_only = True
        except Exception:
            log.debug("module_importer: materials_only rule evaluation failed", exc_info=True)

        theory = extracted_theory_clean
        content_key = None
        if not is_folder:
            if not theory:
                theory = _lesson_markdown_fallback(module_title=module_title, lesson_title=title, files=files)
            content_key = f"{pfx}{order:02d}/theory.md"
            _upload_markdown_text(s3=s3, object_key=content_key, text_value=theory)

        qz = Quiz(type=QuizType.submodule, pass_threshold=70, time_limit=None, attempts_limit=None)
        db.add(qz)
        db.flush()

        s = Submodule(
            module_id=m.id,
            title=title,
            content=theory,
            content_object_key=content_key,
            order=order,
            quiz_id=qz.id,
            requires_quiz=bool(extracted_ok),
            is_folder=bool(is_folder),
            outline_path=outline_path,
        )
        db.add(s)
        db.flush()

        if report is not None:
            report["submodules"] = int(report.get("submodules") or 0) + 1

        # Phase 1: if generate_questions=False (default for fast ingest), create placeholders.
        # Phase 2: if generate_questions=True (background regen), call AI/Heuristic.
        if generate_questions and (not materials_only):
            qs = []
            if settings.openrouter_enabled:
                provider_order = choose_llm_provider_order_fast(ttl_seconds=300, use_cache=False)
                qs = generate_quiz_questions_ai(
                    title=title,
                    text=theory or "",
                    n_questions=5,
                    min_questions=3,
                    retries=3,
                    backoff_seconds=1.0,
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
                                concept_tag=f"ok:import:{m.id}:{order}:{qi}",
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
                                concept_tag=f"heur:import:{m.id}:{order}:{qi}",
                                variant_group=None,
                            )
                        )
                    if report is not None:
                        report["questions_heur"] = int(report.get("questions_heur") or 0) + len(generated)
                        report["questions_total"] = int(report.get("questions_total") or 0) + len(generated)
        else:
            # Quick placeholder creation for two-phase import.
            # Materials-only lessons should NOT require quiz, so skip placeholders.
            if not materials_only:
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
        files_for_assets = files
        if root_as_lesson and i == 1 and extra_assets:
            files_for_assets = list(files) + list(extra_assets)

        seen_asset_paths: set[pathlib.Path] = set()
        for fp in files_for_assets:
            try:
                if not fp.exists() or not fp.is_file():
                    continue
            except Exception:
                continue
            if _should_ignore_file(fp):
                continue
            seen_asset_paths.add(fp)

        for fp in sorted(seen_asset_paths, key=lambda x: _asset_sort_key(fp=x, lesson_root=lesson_root)):
            rel_name = fp.name
            try:
                rel = fp.relative_to(lesson_root)
                rel_name = str(rel.as_posix())
            except Exception:
                rel_name = fp.name

            _set_job_detail(f"asset: {rel_name}")
            object_key = f"{pfx}{order:02d}/{rel_name}"
            mime, size = _upload_file(s3=s3, object_key=object_key, file_path=fp)

            asset = db.scalar(select(ContentAsset).where(ContentAsset.object_key == object_key))
            if asset is None:
                asset = ContentAsset(
                    bucket=settings.s3_bucket,
                    object_key=object_key,
                    original_filename=rel_name,
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

    try:
        any_quiz_required = bool(
            db.scalar(select(func.count(Submodule.id)).where(Submodule.module_id == m.id, Submodule.requires_quiz == True))  # noqa: E712
            or 0
        )
        if not any_quiz_required:
            m.final_quiz_id = None
            db.add(m)
    except Exception:
        log.debug("module_importer: failed to update final_quiz_id", exc_info=True)

    db.commit()
    return m.id
