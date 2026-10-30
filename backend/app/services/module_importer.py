from __future__ import annotations

import logging
import hashlib
import mimetypes
import pathlib
import re
import random
import tempfile
import time
import uuid
import zipfile
import unicodedata

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from rq import get_current_job

from app.core.config import settings
from app.core.redis_client import get_redis
from app.models.asset import ContentAsset
from app.models.module import Module, Submodule
from app.models.quiz import Question, QuestionType, Quiz, QuizType
from app.models.submodule_asset import SubmoduleAssetMap
from app.services.quiz_text import is_useful_quiz_text
from app.services.content import lock_module, module_assets, normalize_name, preserve_progress, snapshot_asset, storage_key, require_owned_asset, snapshot_lesson
from app.services.learning import remember_quiz_version
from app.services.storage import effective_bucket, ensure_bucket_exists, get_s3_client, upload_fileobj_with_retry


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


def _is_noise_dir_name(name: str) -> bool:
    try:
        n = str(name or "").strip()
        nlow = n.lower()
        if not n:
            return True
        if n in {"_module", "__MACOSX"}:
            return True
        if n.startswith("._"):
            return True
        if nlow.startswith("tmp") or nlow.startswith("tmr"):
            return True
        if nlow in {".ds_store", "thumbs.db", "desktop.ini"}:
            return True
    except Exception:
        return False
    return False


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
    if n in {".ds_store", "thumbs.db", "desktop.ini"}:
        return True
    if p.name.startswith("._"):
        return True

    # Ignore tmp-like FILE NAMES commonly created by archivers/editors.
    # This prevents TMPxxxx assets from being treated as standalone "file lessons".
    try:
        stem = str(getattr(p, "stem", "") or "").strip().lower()
        if stem.startswith("tmp") or stem.startswith("tmr"):
            # Keep very short names like "tmp" intact; ignore only realistic temp artifacts.
            if len(stem) >= 6:
                return True
            if re.match(r"^(tmp|tmr)[_-]?\d{2,}$", stem):
                return True
            if re.match(r"^(tmp|tmr)[0-9a-f]{4,}$", stem):
                return True
    except Exception:
        pass
    try:
        parts = list(p.parts or [])
        if "__MACOSX" in set(parts):
            return True
        for i, seg in enumerate(parts):
            s = str(seg or "")
            slow = s.lower()

            # Ignore tmp-like directories *inside* ZIPs (e.g. TMP12345, tmp_01, TMRXXXX),
            # but do NOT ignore system temp roots like '/tmp/tmpxxxx' or '.../Temp/tmpxxxx'
            # which are part of our extraction path.
            if slow.startswith("tmp") or slow.startswith("tmr"):
                if slow in {"tmp", "tmr"}:
                    continue

                prev = str(parts[i - 1] or "").lower() if i > 0 else ""
                prev2 = str(parts[i - 2] or "").lower() if i > 1 else ""
                if prev in {"tmp", "temp", "temporaryitems"}:
                    continue
                if prev2 in {"tmp", "temp", "temporaryitems"}:
                    continue
                if prev.endswith("temp") or prev2.endswith("temp"):
                    continue

                if len(s) >= 6:
                    return True
                if re.match(r"^(tmp|tmr)[_-]?\d{2,}$", slow):
                    return True
                if re.match(r"^(tmp|tmr)[0-9a-f]{4,}$", slow):
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
        direct_dirs = [p for p in root.iterdir() if p.is_dir() and (not _is_noise_dir_name(p.name))]
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
        from app.services.document_preview import MAX_BYTES, build_preview
        if path.stat().st_size > MAX_BYTES:
            return ""
        preview = build_preview(path.read_bytes(), path.name)
        return "\n\n".join(part["text"] for part in preview.get("blocks", []))[:300_000]
    except Exception:
        return ""


def _pdf_to_text(path: pathlib.Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        if path.stat().st_size > 25 * 1024 * 1024:
            return ""
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages[:30]:
            t = page.extract_text() or ""
            t = _normalize_text_to_markdown(t)
            if t:
                parts.append(t)
        return "\n\n".join(parts).strip()[:300_000]
    except Exception:
        return ""


def _read_text(path: pathlib.Path) -> str:
    ext = path.suffix.lower()
    if ext in {".txt", ".md"}:
        try:
            with path.open("rb") as stream:
                txt = stream.read(2 * 1024 * 1024).decode("utf-8", errors="replace")[:300_000]
            if ext == ".md":
                return txt.strip()
            return _normalize_text_to_markdown(txt)
        except Exception:
            return ""
    if ext in {".docx", ".pptx"}:
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


def _maybe_transcode_video(*, file_path: pathlib.Path, rel_name: str) -> tuple[pathlib.Path, str, str | None]:
    """Legacy helper: imports always retain exact originals; conversion is async."""
    return file_path, rel_name, None


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


def _source_path(path: pathlib.Path, root: pathlib.Path) -> str:
    value = normalize_name(path.relative_to(root).as_posix())
    if len(value) > 1000:
        raise ValueError("Путь внутри ZIP слишком длинный (более 1000 символов)")
    return value


def _import_specs(root: pathlib.Path) -> list[dict]:
    """Stable identities are paths, NEVER ordinal lesson numbers.

    Root files are lessons; top-level directories are material catalogs. _module
    contains general attachments. A missing path in a new ZIP is kept, not deleted.
    """
    specs = []
    entries = sorted(root.iterdir(), key=lambda p: (_parse_order(p.name, 999), p.name.casefold()))
    for path in entries:
        if _should_ignore_file(path):
            continue
        if path.name == "_module" and path.is_dir():
            for fp in _list_files_recursive(path):
                specs.append({"source": _source_path(fp, root), "title": fp.name,
                              "files": [fp], "root": path, "folder": False, "general": True})
        elif path.is_file():
            specs.append({"source": "file:" + _source_path(path, root), "title": _guess_title(path.stem),
                          "files": [path], "root": root, "folder": False, "general": False})
        elif path.is_dir() and not _is_noise_dir_name(path.name):
            files = _list_files_recursive(path)
            if files:
                specs.append({"source": "folder:" + _source_path(path, root), "title": _guess_title(path.name),
                              "files": files, "root": path, "folder": True, "general": False})
    if not specs:
        raise ValueError("ZIP не содержит материалов для импорта")
    return specs


def import_module_from_dir(
    *, db: Session, module_dir: pathlib.Path, title_override: str | None = None,
    report_out: dict | None = None, generate_questions: bool = False,
    module_id_override: str | None = None, expected_revision: int | None = None,
    require_new_quizzes: bool = False,
) -> uuid.UUID:
    """Stage immutable S3 objects, then atomically merge DB references.

    No deletes, hidden publication changes, commits, or questionnaire replacement.
    The caller owns the transaction. A failed update leaves live bytes and IDs intact.
    """
    ensure_bucket_exists()
    s3 = get_s3_client()
    bucket = effective_bucket()
    module_title = normalize_name(title_override or module_dir.name) or "Модуль"
    mid = uuid.UUID(str(module_id_override)) if module_id_override else uuid.uuid4()
    existing = db.get(Module, mid) if module_id_override else None
    if module_id_override and existing is None:
        raise ValueError("Модуль для обновления не найден")
    if existing is None and db.scalar(select(Module.id).where(func.lower(Module.title) == module_title.lower())):
        raise ValueError("Модуль с таким названием уже существует")
    if existing and existing.is_archived:
        raise ValueError("Сначала восстановите модуль из архива")
    base_revision = existing.content_revision if existing else 1
    if expected_revision is not None and base_revision != expected_revision:
        raise ValueError("Модуль изменён после запуска импорта. Обновите страницу и повторите.")
    prefix = (existing.storage_prefix if existing else None) or f"modules/{_slugify_s3_segment(module_title)}__{mid}/"
    staging_module = Module(id=mid, title=module_title, storage_prefix=prefix)
    known_assets = module_assets(db, mid) if existing else []
    source_hashes = {a.source_path: a.source_checksum_sha256 for a in known_assets if a.source_path}
    known_hashes = {a.source_path: a.checksum_sha256 for a in known_assets if a.source_path}
    # End the read transaction before potentially long S3 uploads. No locks while
    # transcoding/uploading: learners continue using the previous content revision.
    db.rollback()

    report = report_out if report_out is not None else {}
    report.update({"module_title": module_title, "submodules": 0, "lesson_assets": 0, "module_assets": 0,
                   "lessons_added": 0, "lessons_updated": 0, "lessons_kept": 0,
                   "files_added": 0, "files_updated": 0, "files_unchanged": 0,
                   "questions_total": 0, "needs_regen": 0, "progress_preserved": True,
                   "warnings": []})
    specs = _import_specs(module_dir)
    uploaded: list[str] = []
    try:
        # Phase 1: validation/extraction/upload, no DB mutations.
        for spec in specs:
            _set_job_detail(f"Подготовка: {spec['title']}")
            theory = "" if spec["folder"] or spec["general"] else _theory_from_files(spec["files"])
            spec["theory"] = theory
            spec["requires_quiz"] = False  # Tests are a separate, reviewed authoring action.
            spec["assets"] = []
            for fp in sorted(spec["files"], key=lambda p: _asset_sort_key(fp=p, lesson_root=spec["root"])):
                source = _source_path(fp, module_dir)
                rel_name = normalize_name(fp.relative_to(spec["root"]).as_posix())
                if len(rel_name) > 400:
                    raise ValueError(f"Слишком длинное имя файла: {rel_name[:80]}")
                with fp.open("rb") as stream:
                    source_checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                if source_hashes.get(source) == source_checksum:
                    spec["assets"].append({"source": source, "filename": rel_name, "key": None,
                                           "source_checksum": source_checksum, "source_unchanged": True})
                    continue
                # Publish the exact original; expensive encoding is a separate outbox job.
                eff_path, eff_rel, forced_ct = fp, rel_name, None
                try:
                    with eff_path.open("rb") as stream:
                        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                    key = None
                    mime = forced_ct or mimetypes.guess_type(eff_rel)[0] or "application/octet-stream"
                    size = eff_path.stat().st_size
                    if known_hashes.get(source) != checksum:
                        key = storage_key(staging_module, eff_rel)
                        # Register BEFORE uploading, including cleanup of partial failures.
                        uploaded.append(key)
                        _upload_file(s3=s3, object_key=key, file_path=eff_path)
                    spec["assets"].append({"source": source, "filename": eff_rel, "key": key,
                                           "mime": mime, "size": size, "checksum": checksum,
                                           "source_checksum": source_checksum, "source_unchanged": False})
                finally:
                    if eff_path != fp:
                        eff_path.unlink(missing_ok=True)
                        if eff_path.parent.name.startswith("corelms_transcode_"):
                            eff_path.parent.rmdir()

        # Phase 2: short atomic reconciliation, with optimistic conflict detection.
        if module_id_override:
            module = lock_module(db, mid, base_revision)
            if module.is_archived:
                raise ValueError("Модуль перемещён в архив во время импорта")
            preserve_progress(db, module)
        else:
            module = Module(id=mid, title=module_title, description=f"Материалы модуля «{module_title}».",
                            difficulty=1, category="Обучение", is_active=False, storage_prefix=prefix)
            db.add(module)
            db.flush()
        module.storage_prefix = prefix
        old_subs = list(db.scalars(select(Submodule).where(Submodule.module_id == mid).order_by(Submodule.order)))
        assets = module_assets(db, mid)
        linked = dict(db.execute(select(SubmoduleAssetMap.asset_id, SubmoduleAssetMap.submodule_id).where(
            SubmoduleAssetMap.submodule_id.in_([s.id for s in old_subs])
        )).all())
        used: set[uuid.UUID] = set()
        max_order = max([s.order for s in old_subs] + [0])
        for spec in specs:
            sub = None
            new_lesson = False
            if not spec["general"]:
                candidates = [s for s in old_subs if s.id not in used and s.source_path == spec["source"]]
                if not candidates:
                    # Conservative legacy adoption: only an unambiguous title + kind.
                    # Never match by order or a fuzzy title; ambiguity must not move progress.
                    candidates = [s for s in old_subs if s.id not in used and not s.source_path
                                  and normalize_name(s.title).casefold() == normalize_name(spec["title"]).casefold()
                                  and s.is_folder == spec["folder"]]
                if len(candidates) == 1:
                    sub = candidates[0]
                    report["lessons_updated"] += 1
                    if sub.content != spec["theory"]:
                        if sub.content_mode == "manual":
                            report["warnings"].append(f"«{sub.title}»: ручной текст сохранён; обновлены только вложения.")
                        else:
                            snapshot_lesson(db, sub)
                            sub.content = spec["theory"]
                            sub.content_object_key = None
                            if sub.requires_quiz:
                                report["warnings"].append(f"«{sub.title}»: текст обновлён; проверьте соответствие сохранённого теста.")
                    # Names, ordering, quiz policy, archived state and manual text remain intact.
                    sub.source_path = spec["source"]
                else:
                    if candidates:
                        report["warnings"].append(f"«{spec['title']}»: неоднозначное сопоставление; создан новый материал, старые сохранены.")
                    quiz = Quiz(type=QuizType.submodule, pass_threshold=70, attempts_limit=0)
                    db.add(quiz)
                    db.flush()
                    max_order += 1
                    sub = Submodule(module_id=mid, title=spec["title"][:300], content=spec["theory"],
                                    order=max_order, quiz_id=quiz.id, requires_quiz=spec["requires_quiz"],
                                    is_folder=spec["folder"], source_path=spec["source"], content_mode="import")
                    db.add(sub)
                    db.flush()
                    new_lesson = True
                    report["lessons_added"] += 1
                used.add(sub.id)
                remember_quiz_version(db, sub)
                report["submodules"] += 1

            for data in spec["assets"]:
                target = sub.id if sub else None
                matches = [a for a in assets if a.source_path == data["source"]]
                if not matches:
                    matches = [a for a in assets if not a.source_path and linked.get(a.id) == target
                               and normalize_name(a.original_filename).casefold() == normalize_name(data["filename"]).casefold()]
                if len(matches) > 1:
                    raise ValueError(f"Несколько файлов соответствуют {data['filename']}. Уточните структуру в редакторе.")
                if matches and not matches[0].source_path and matches[0].created_by is not None:
                    raise ValueError(f"«{data['filename']}» уже добавлен вручную. Переименуйте файл в ZIP или редакторе, чтобы импорт не заменил его без явной привязки к источнику.")
                asset = require_owned_asset(db, module, matches[0].id) if matches else None
                if asset is None:
                    if not data["key"]:
                        raise ValueError("Файл перемещён в редакторе во время подготовки. Повторите импорт.")
                    asset = ContentAsset(module_id=mid, bucket=bucket, object_key=data["key"],
                        original_filename=data["filename"], mime_type=data["mime"], size_bytes=data["size"],
                        checksum_sha256=data["checksum"], source_checksum_sha256=data["source_checksum"], source_path=data["source"], order=len(assets) + 1)
                    db.add(asset)
                    db.flush()
                    assets.append(asset)
                    if sub:
                        order = int(db.scalar(select(func.max(SubmoduleAssetMap.order)).where(SubmoduleAssetMap.submodule_id == sub.id)) or 0) + 1
                        db.add(SubmoduleAssetMap(submodule_id=sub.id, asset_id=asset.id, order=order))
                        db.flush()
                        linked[asset.id] = sub.id
                    report["files_added"] += 1
                elif not data["source_unchanged"] and asset.checksum_sha256 != data["checksum"]:
                    if not data["key"]:
                        raise ValueError("Версия файла изменилась. Повторите импорт.")
                    snapshot_asset(db, asset)
                    asset.object_key, asset.bucket = data["key"], bucket
                    asset.mime_type, asset.size_bytes = data["mime"], data["size"]
                    asset.checksum_sha256 = data["checksum"]
                    asset.source_checksum_sha256 = data["source_checksum"]
                    asset.source_path = data["source"]
                    asset.module_id = mid
                    report["files_updated"] += 1
                else:
                    asset.source_path = data["source"]
                    asset.source_checksum_sha256 = data["source_checksum"]
                    report["files_unchanged"] += 1
                    if data["key"]:
                        s3.delete_object(Bucket=bucket, Key=data["key"])
                        uploaded.remove(data["key"])
                if sub and new_lesson and not sub.is_folder and sub.primary_asset_id is None:
                    sub.primary_asset_id = asset.id
                from app.services.media import stage_rendition
                from app.services.thumbs import enqueue_thumb
                db.flush()
                stage_rendition(db, asset)
                enqueue_thumb(asset.id)
                report["lesson_assets" if sub else "module_assets"] += 1
        report["lessons_kept"] = len([s for s in old_subs if s.id not in used])
        db.flush()
        if not module_id_override and module.final_quiz_id is None and db.scalar(select(Submodule.id).where(
            Submodule.module_id == mid, Submodule.requires_quiz.is_(True), Submodule.is_archived.is_(False)
        ).limit(1)):
            final = Quiz(type=QuizType.final, pass_threshold=70, attempts_limit=3)
            db.add(final)
            db.flush()
            module.final_quiz_id = final.id
        module.content_revision += 1
        report["content_revision"] = module.content_revision
        db.flush()
        return mid
    except Exception:
        db.rollback()
        # Only unique staging keys from THIS attempt; never a live or source object.
        for key in uploaded:
            try:
                s3.delete_object(Bucket=bucket, Key=key)
            except Exception:
                log.warning("Could not remove staged object %s", key)
        raise
