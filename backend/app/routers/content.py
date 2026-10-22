"""Module authoring API. All mutations are scoped, revision-checked and audited."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import pathlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.queue import get_queue, fetch_job, get_job_status, release_job_lock
from app.core.redis_client import get_redis
from app.core.rate_limit import rate_limit
from app.core.security import require_roles
from app.core.security_audit_log import audit_log
from app.db.session import get_db
from app.models.asset import AssetRevision, ContentAsset
from app.models.module import Module, Submodule
from app.models.lesson_revision import LessonRevision
from app.models.quiz import Question, QuestionType, Quiz, QuizType
from app.schemas.authoring import FinalQuizSave, GenerateDraft, GenerateModuleDrafts, QuizSave
from app.services.quiz_drafts import prepare_module_drafts, module_draft_status
from app.services.authoring import format_prompt, generate_quiz_draft_job, question_payload, quiz_payload, source_revision, request_signature
from app.models.submodule_asset import SubmoduleAssetMap
from app.models.tag import ModuleTagMap, Tag
from app.services.media import stage_rendition
from app.models.user import User, UserRole
from app.schemas.content import ArchiveAssets, AssetEdit, LessonDraft, LessonEdit, ModuleDraft, ModuleEdit, ReorderRequest, VersionRestore
from app.services.content import (ensure_filename_available, lock_module, next_lesson_order, normalize_name,
    preserve_progress, reorder_lessons, require_lesson, require_owned_asset, safe_filename, snapshot_asset,
    storage_key, workspace, snapshot_lesson, read_lesson_text)
from app.services.learning import remember_quiz_version
from app.services.modules import modules_bump_rev
from app.services.storage import effective_bucket, get_s3_client, upload_fileobj_with_retry

router = APIRouter(prefix="/admin/content/modules", tags=["content editor"], dependencies=[Depends(require_roles(UserRole.admin))])


def _finish(db: Session, request: Request, user: User, module: Module, action: str, **meta) -> dict:
    module.content_revision += 1
    audit_log(db=db, request=request, actor_user_id=user.id, event_type=action,
              meta={"module_id": str(module.id), "content_revision": module.content_revision, **meta})
    db.commit()
    modules_bump_rev(reason=action)
    return workspace(db, module)


def _editable(db: Session, module_id: uuid.UUID, revision: int) -> Module:
    module = lock_module(db, module_id, revision)
    if module.is_archived:
        raise HTTPException(409, "Сначала восстановите модуль из архива")
    return module


def _check_publishable(db: Session, module: Module) -> None:
    lessons = list(db.scalars(select(Submodule).where(Submodule.module_id == module.id, Submodule.is_archived.is_(False))))
    for sub in lessons:
        if not sub.is_folder and not str(sub.content or "").strip() and not sub.content_object_key and not db.scalar(
            select(ContentAsset.id).join(SubmoduleAssetMap, SubmoduleAssetMap.asset_id == ContentAsset.id)
            .where(SubmoduleAssetMap.submodule_id == sub.id, ContentAsset.is_archived.is_(False)).limit(1)):
            raise HTTPException(409, f"В уроке «{sub.title}» пока нет текста или файлов")
        if not sub.requires_quiz or sub.is_folder:
            continue
        questions = list(db.scalars(select(Question).where(Question.quiz_id == sub.quiz_id)))
        if not questions or any(str(q.concept_tag or "").startswith("needs_regen:") or not question_payload(q)["valid"] for q in questions):
            raise HTTPException(409, f"В уроке «{sub.title}» тест ещё не готов. Подготовьте вопросы или выключите обязательный тест.")
    if not lessons and not db.scalar(select(ContentAsset.id).where(ContentAsset.module_id == module.id, ContentAsset.is_archived.is_(False)).limit(1)):
        raise HTTPException(409, "Добавьте хотя бы один урок или файл перед публикацией")


@router.get("")
def list_workspaces(include_archived: bool = False, db: Session = Depends(get_db)):
    stmt = select(Module).order_by(Module.title)
    if not include_archived:
        stmt = stmt.where(Module.is_archived.is_(False))
    lesson_counts = dict(db.execute(select(Submodule.module_id, func.count()).where(Submodule.is_archived.is_(False)).group_by(Submodule.module_id)).all())
    asset_counts = dict(db.execute(select(ContentAsset.module_id, func.count()).where(ContentAsset.is_archived.is_(False)).group_by(ContentAsset.module_id)).all())
    return {"items": [{"id": str(m.id), "title": m.title, "is_archived": m.is_archived, "is_active": m.is_active,
                        "category": m.category, "description": m.description,
                        "lesson_count": lesson_counts.get(m.id, 0), "asset_count": asset_counts.get(m.id, 0),
                        "content_revision": m.content_revision} for m in db.scalars(stmt)]}



@router.post("", status_code=201)
def create_workspace(body: ModuleDraft, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin))):
    if db.scalar(select(Module.id).where(func.lower(Module.title) == body.title.lower())):
        raise HTTPException(409, "Модуль с таким названием уже существует")
    module = Module(title=body.title, description=body.description, category=body.category, is_active=False)
    db.add(module)
    db.flush()
    return _finish(db, request, user, module, "content_module_created")


@router.get("/{module_id}")
def get_workspace(module_id: uuid.UUID, db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(404, "Модуль не найден")
    return workspace(db, module)


@router.patch("/{module_id}")
def edit_workspace(module_id: uuid.UUID, body: ModuleEdit, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin))):
    module = lock_module(db, module_id, body.revision)
    preserve_progress(db, module)
    if body.title is not None:
        if db.scalar(select(Module.id).where(Module.id != module.id, func.lower(Module.title) == body.title.lower())):
            raise HTTPException(409, "Модуль с таким названием уже существует")
        module.title = body.title
    for field in ("description", "category"):
        if field in body.model_fields_set:
            setattr(module, field, getattr(body, field))
    if body.visibility is not None:
        module.visibility = body.visibility
    if body.tag_ids is not None:
        wanted = set(body.tag_ids)
        if wanted != set(db.scalars(select(Tag.id).where(Tag.id.in_(wanted)))):
            raise HTTPException(422, "Указаны неизвестные теги доступа")
        db.execute(delete(ModuleTagMap).where(ModuleTagMap.module_id == module.id))
        for tid in wanted:
            db.add(ModuleTagMap(module_id=module.id, tag_id=tid))
    if body.is_archived is not None:
        module.is_archived = body.is_archived
        # Restoring is deliberate, publishing is a separate action.
        module.is_active = False
    if body.is_active is not None:
        if body.is_active:
            if module.is_archived:
                raise HTTPException(409, "Модуль находится в архиве")
            _check_publishable(db, module)
        module.is_active = body.is_active
    return _finish(db, request, user, module, "content_module_updated", fields=sorted(body.model_fields_set - {"revision"}))


@router.post("/{module_id}/lessons", status_code=201)
def create_lesson(module_id: uuid.UUID, body: LessonDraft, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin))):
    module = _editable(db, module_id, body.revision)
    preserve_progress(db, module)
    quiz = Quiz(type=QuizType.submodule, pass_threshold=70, attempts_limit=0)
    db.add(quiz)
    db.flush()
    lesson = Submodule(module_id=module.id, title=body.title, content=body.content, is_folder=body.is_folder,
                       outline_path=body.outline_path, presentation_mode=body.presentation_mode, requires_quiz=False, quiz_id=quiz.id, order=next_lesson_order(db, module))
    db.add(lesson)
    db.flush()
    remember_quiz_version(db, lesson)
    return _finish(db, request, user, module, "content_lesson_created", submodule_id=str(lesson.id))


@router.patch("/{module_id}/lessons/{lesson_id}")
def edit_lesson(module_id: uuid.UUID, lesson_id: uuid.UUID, body: LessonEdit, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin))):
    module = _editable(db, module_id, body.revision)
    lesson = require_lesson(db, module, lesson_id)
    preserve_progress(db, module)
    if body.title is not None:
        lesson.title = body.title
    if body.presentation_mode is not None:
        lesson.presentation_mode = body.presentation_mode
    if "primary_asset_id" in body.model_fields_set:
        if body.primary_asset_id:
            asset = require_owned_asset(db, module, body.primary_asset_id)
            if asset.is_archived or not db.scalar(select(SubmoduleAssetMap.asset_id).where(SubmoduleAssetMap.asset_id == asset.id, SubmoduleAssetMap.submodule_id == lesson.id)):
                raise HTTPException(422, "Основной файл должен быть активным файлом этого урока")
        lesson.primary_asset_id = body.primary_asset_id
    content_changed = body.content is not None and (body.content != lesson.content or bool(lesson.content_object_key))
    mode = body.content_mode or ("manual" if content_changed else lesson.content_mode)
    if mode == "import" and not lesson.source_path:
        raise HTTPException(422, "Урок создан вручную: для него нет исходного текста в ZIP")
    if content_changed or mode != lesson.content_mode:
        snapshot_lesson(db, lesson, user_id=user.id)
    if content_changed:
        lesson.content = body.content
        lesson.content_object_key = None
    lesson.content_mode = mode
    if "outline_path" in body.model_fields_set:
        lesson.outline_path = normalize_name(body.outline_path or "") or None
    if body.requires_quiz is not None:
        if body.requires_quiz:
            if lesson.is_folder:
                raise HTTPException(422, "Каталог материалов не может требовать тест")
            ready = db.scalar(select(Question.id).where(Question.quiz_id == lesson.quiz_id,
                ~func.coalesce(Question.concept_tag, "").like("needs_regen:%")).limit(1))
            if ready is None:
                raise HTTPException(409, "Сначала подготовьте вопросы теста")
        lesson.requires_quiz = body.requires_quiz
    if body.is_archived is not None:
        lesson.is_archived = body.is_archived
    return _finish(db, request, user, module, "content_lesson_updated", submodule_id=str(lesson.id), fields=sorted(body.model_fields_set - {"revision"}))


@router.get("/{module_id}/lessons/{lesson_id}/content")
def lesson_text(module_id: uuid.UUID, lesson_id: uuid.UUID, db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(404, "Модуль не найден")
    lesson = require_lesson(db, module, lesson_id)
    return {"content": read_lesson_text(lesson.content, lesson.content_object_key),
            "content_version": lesson.content_version, "revision": module.content_revision}


@router.get("/{module_id}/lessons/{lesson_id}/versions")
def lesson_versions(module_id: uuid.UUID, lesson_id: uuid.UUID, db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(404, "Модуль не найден")
    lesson = require_lesson(db, module, lesson_id)
    versions = db.scalars(select(LessonRevision).where(LessonRevision.submodule_id == lesson.id)
                         .order_by(LessonRevision.version.desc())).all()
    # Text is fetched separately, not repeated for every history entry.
    return {"current_version": lesson.content_version, "items": [
        {"version": v.version, "created_at": v.created_at.isoformat(), "content_mode": v.content_mode}
        for v in versions]}


@router.get("/{module_id}/lessons/{lesson_id}/versions/{version_number}")
def lesson_version_text(module_id: uuid.UUID, lesson_id: uuid.UUID, version_number: int, db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(404, "Модуль не найден")
    lesson = require_lesson(db, module, lesson_id)
    version = db.scalar(select(LessonRevision).where(LessonRevision.submodule_id == lesson.id,
                                                   LessonRevision.version == version_number))
    if version is None:
        raise HTTPException(404, "Версия текста не найдена")
    return {"version": version.version, "content": read_lesson_text(version.content, version.content_object_key, version.bucket)}


@router.post("/{module_id}/lessons/{lesson_id}/restore-version")
def restore_lesson_version(module_id: uuid.UUID, lesson_id: uuid.UUID, body: VersionRestore, request: Request,
                           db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin))):
    module = _editable(db, module_id, body.revision)
    lesson = require_lesson(db, module, lesson_id)
    if lesson.is_archived:
        raise HTTPException(409, "Сначала восстановите урок из архива")
    source = lesson_version_text(module_id, lesson_id, body.version, db)
    snapshot_lesson(db, lesson, user_id=user.id)
    lesson.content, lesson.content_object_key, lesson.content_mode = source["content"], None, "manual"
    return _finish(db, request, user, module, "content_lesson_version_restored",
                   submodule_id=str(lesson.id), source_version=body.version)


@router.put("/{module_id}/lesson-order")
def change_lesson_order(module_id: uuid.UUID, body: ReorderRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin))):
    module = _editable(db, module_id, body.revision)
    reorder_lessons(db, module, body.ids)
    return _finish(db, request, user, module, "content_lessons_reordered")


def _inspect_upload(file: UploadFile, *, max_bytes: int) -> tuple[str, int, str]:
    name = safe_filename(file.filename or "")
    file.file.seek(0, 2)
    size = file.file.tell()
    if size <= 0:
        raise HTTPException(422, "Файл пустой")
    if size > max_bytes:
        raise HTTPException(413, f"Файл превышает лимит {max_bytes // (1024 * 1024)} МБ")
    file.file.seek(0)
    checksum = hashlib.file_digest(file.file, "sha256").hexdigest()
    file.file.seek(0)
    return name, size, checksum


@router.post("/{module_id}/assets", status_code=201)
def upload_asset(
    module_id: uuid.UUID, request: Request, file: UploadFile = File(...), revision: int = Form(..., ge=1),
    submodule_id: uuid.UUID | None = Form(default=None), replace_asset_id: uuid.UUID | None = Form(default=None),
    create_lesson: bool = Form(default=False),
    db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="content_upload", limit=120, window_seconds=60),
):
    filename, size, checksum = _inspect_upload(file, max_bytes=int(getattr(settings, "content_upload_max_bytes", 512 * 1024 * 1024)))
    if create_lesson and (submodule_id or replace_asset_id):
        raise HTTPException(422, "Создание урока нельзя объединять с заменой или перемещением файла")
    # Validate before transferring bytes, then recheck revision under lock after upload.
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(404, "Модуль не найден")
    if module.content_revision != revision or module.is_archived:
        raise HTTPException(409, "Модуль изменён или находится в архиве. Обновите данные.")
    if submodule_id:
        sub = require_lesson(db, module, submodule_id)
        if sub.is_archived:
            raise HTTPException(409, "Сначала восстановите урок из архива")
    asset = require_owned_asset(db, module, replace_asset_id) if replace_asset_id else None
    if asset:
        # A replace keeps the logical location and display name, not a client-supplied move.
        submodule_id = db.scalar(select(SubmoduleAssetMap.submodule_id).where(SubmoduleAssetMap.asset_id == asset.id))
    elif not create_lesson:
        ensure_filename_available(db, module, filename, submodule_id)
    key = storage_key(module, filename)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    db.rollback()
    s3 = get_s3_client()
    bucket = effective_bucket()
    commit_attempted = False
    created_lesson = None
    try:
        upload_fileobj_with_retry(s3=s3, object_key=key, fileobj=file.file, content_type=mime, size_bytes=size)
        module = _editable(db, module_id, revision)
        if create_lesson:
            preserve_progress(db, module)
            title = pathlib.PurePosixPath(filename).stem.strip()[:280] or "Новый урок"
            names = {name.casefold() for name in db.scalars(select(Submodule.title).where(Submodule.module_id == module.id, Submodule.is_archived.is_(False)))}
            original_title, suffix = title, 2
            while title.casefold() in names:
                title = f"{original_title} ({suffix})"; suffix += 1
            quiz = Quiz(type=QuizType.submodule, pass_threshold=70, attempts_limit=0)
            db.add(quiz); db.flush()
            created_lesson = Submodule(module_id=module.id, title=title, content="", order=next_lesson_order(db, module),
                quiz_id=quiz.id, requires_quiz=False, is_folder=False, presentation_mode="material", content_mode="manual")
            db.add(created_lesson); db.flush()
            submodule_id = created_lesson.id
            remember_quiz_version(db, created_lesson)
        if submodule_id and require_lesson(db, module, submodule_id).is_archived:
            raise HTTPException(409, "Урок перемещён в архив")
        if replace_asset_id:
            asset = require_owned_asset(db, module, replace_asset_id)
            if asset.is_archived:
                raise HTTPException(409, "Сначала восстановите файл из архива")
            if pathlib.PurePath(filename).suffix.lower() != pathlib.PurePath(asset.original_filename).suffix.lower():
                raise HTTPException(422, "При замене сохраните формат файла. Другой формат добавьте отдельным материалом.")
            snapshot_asset(db, asset)
            asset.object_key, asset.mime_type, asset.size_bytes, asset.bucket = key, mime, size, bucket
            asset.checksum_sha256, asset.created_by = checksum, user.id
        else:
            ensure_filename_available(db, module, filename, submodule_id)
            asset = ContentAsset(module_id=module.id, bucket=bucket, object_key=key,
                original_filename=filename, mime_type=mime, size_bytes=size, checksum_sha256=checksum, created_by=user.id,
                order=int(db.scalar(select(func.max(ContentAsset.order)).where(ContentAsset.module_id == module.id)) or 0) + 1)
            db.add(asset)
            db.flush()
            if submodule_id:
                position = int(db.scalar(select(func.max(SubmoduleAssetMap.order)).where(SubmoduleAssetMap.submodule_id == submodule_id)) or 0) + 1
                db.add(SubmoduleAssetMap(submodule_id=submodule_id, asset_id=asset.id, order=position))
        if created_lesson:
            created_lesson.primary_asset_id = asset.id
        db.flush()
        stage_rendition(db, asset)
        # File changes alone do not change required learning steps.
        module.content_revision += 1
        audit_log(db=db, request=request, actor_user_id=user.id, event_type="content_asset_replaced" if replace_asset_id else "content_asset_uploaded",
                  meta={"module_id": str(module.id), "asset_id": str(asset.id), "version": asset.version, "size_bytes": size})
        commit_attempted = True
        db.commit()
        modules_bump_rev(reason="content_asset_changed")
        state = workspace(db, module)
        if created_lesson:
            state["created_lesson_id"] = str(created_lesson.id)
        return state
    except Exception:
        db.rollback()
        if not commit_attempted:
            try:
                s3.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass  # Unique orphan may be cleaned later; never delete a previous version.
        raise


@router.patch("/{module_id}/assets/{asset_id}")
def edit_asset(module_id: uuid.UUID, asset_id: uuid.UUID, body: AssetEdit, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin))):
    module = _editable(db, module_id, body.revision)
    asset = require_owned_asset(db, module, asset_id)
    preserve_progress(db, module)
    current_lesson = db.scalar(select(SubmoduleAssetMap.submodule_id).where(SubmoduleAssetMap.asset_id == asset.id))
    target = body.submodule_id if "submodule_id" in body.model_fields_set else current_lesson
    if target and require_lesson(db, module, target).is_archived:
        raise HTTPException(409, "Сначала восстановите урок из архива")
    filename = safe_filename(body.filename) if body.filename is not None else asset.original_filename
    if body.filename is not None and "/" in asset.original_filename:
        filename = f"{asset.original_filename.rsplit('/', 1)[0]}/{filename}"
    if len(filename) > 400:
        raise HTTPException(422, "Слишком длинное имя файла с учётом папки")
    if body.filename is not None and pathlib.PurePath(filename).suffix.lower() != pathlib.PurePath(asset.original_filename).suffix.lower():
        raise HTTPException(422, "Расширение файла менять нельзя. Загрузите новый файл через «Заменить».")
    if not (body.is_archived is True):
        ensure_filename_available(db, module, filename, target, exclude=asset.id)
    asset.original_filename = filename
    if body.is_archived is not None:
        asset.is_archived = body.is_archived
    if "submodule_id" in body.model_fields_set and target != current_lesson:
        db.execute(delete(SubmoduleAssetMap).where(SubmoduleAssetMap.asset_id == asset.id))
        if target:
            order = int(db.scalar(select(func.max(SubmoduleAssetMap.order)).where(SubmoduleAssetMap.submodule_id == target)) or 0) + 1
            db.add(SubmoduleAssetMap(submodule_id=target, asset_id=asset.id, order=order))
    return _finish(db, request, user, module, "content_asset_updated", asset_id=str(asset.id), fields=sorted(body.model_fields_set - {"revision"}))


@router.post("/{module_id}/assets/archive")
def archive_assets(module_id: uuid.UUID, body: ArchiveAssets, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin))):
    module = _editable(db, module_id, body.revision)
    preserve_progress(db, module)
    for aid in set(body.ids):
        asset = require_owned_asset(db, module, aid)
        if not body.is_archived:
            location = db.scalar(select(SubmoduleAssetMap.submodule_id).where(SubmoduleAssetMap.asset_id == aid))
            ensure_filename_available(db, module, asset.original_filename, location, exclude=aid)
        asset.is_archived = body.is_archived
        db.flush()
    return _finish(db, request, user, module, "content_assets_archived" if body.is_archived else "content_assets_restored", asset_ids=[str(a) for a in body.ids])


@router.put("/{module_id}/asset-order")
def change_asset_order(module_id: uuid.UUID, body: ReorderRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin))):
    module = _editable(db, module_id, body.revision)
    state = workspace(db, module)
    location = str(body.submodule_id) if body.submodule_id else None
    active = {uuid.UUID(a["asset_id"]) for a in state["assets"] if not a["is_archived"] and a["submodule_id"] == location}
    if set(body.ids) != active or len(set(body.ids)) != len(body.ids):
        raise HTTPException(422, "Передайте все активные файлы выбранного раздела ровно один раз")
    maps = list(db.scalars(select(SubmoduleAssetMap).where(SubmoduleAssetMap.submodule_id == body.submodule_id))) if body.submodule_id else []
    low = min([link.order for link in maps] + [0]) - len(maps) - 1
    for i, link in enumerate(maps):
        link.order = low + i
    db.flush()
    order = {aid: i for i, aid in enumerate(body.ids, 1)}
    for link in maps:
        if link.asset_id not in order:
            order[link.asset_id] = len(order) + 1
        link.order = order[link.asset_id]
    for aid, position in order.items():
        require_owned_asset(db, module, aid).order = position
    return _finish(db, request, user, module, "content_assets_reordered")


@router.get("/{module_id}/assets/{asset_id}/versions")
def asset_versions(module_id: uuid.UUID, asset_id: uuid.UUID, db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(404, "Модуль не найден")
    asset = require_owned_asset(db, module, asset_id)
    versions = list(db.scalars(select(AssetRevision).where(AssetRevision.asset_id == asset.id).order_by(AssetRevision.version.desc())))
    return {"current_version": asset.version, "items": [{"version": v.version, "filename": v.original_filename,
            "size_bytes": v.size_bytes, "created_at": v.created_at.isoformat()} for v in versions]}


@router.post("/{module_id}/assets/{asset_id}/restore-version")
def restore_asset_version(module_id: uuid.UUID, asset_id: uuid.UUID, body: VersionRestore, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin))):
    module = _editable(db, module_id, body.revision)
    asset = require_owned_asset(db, module, asset_id)
    version = db.scalar(select(AssetRevision).where(AssetRevision.asset_id == asset.id, AssetRevision.version == body.version))
    if version is None:
        raise HTTPException(404, "Версия не найдена")
    try:
        get_s3_client().head_object(Bucket=version.bucket, Key=version.object_key)
    except Exception as exc:
        raise HTTPException(409, "Оригинал этой версии недоступен в хранилище") from exc
    restored_suffix = pathlib.PurePosixPath(version.original_filename).suffix
    restored_name = str(pathlib.PurePosixPath(asset.original_filename).with_suffix(restored_suffix))
    lesson_id = db.scalar(select(SubmoduleAssetMap.submodule_id).where(SubmoduleAssetMap.asset_id == asset.id))
    ensure_filename_available(db, module, restored_name, lesson_id, exclude=asset.id)
    snapshot_asset(db, asset)
    asset.original_filename = restored_name
    asset.object_key, asset.bucket, asset.mime_type = version.object_key, version.bucket, version.mime_type
    asset.size_bytes, asset.checksum_sha256, asset.created_by = version.size_bytes, version.checksum_sha256, user.id
    db.flush()
    stage_rendition(db, asset)
    # Keep the current display name/location. Restoring is a new version, not history rewriting.
    return _finish(db, request, user, module, "content_asset_version_restored", asset_id=str(asset.id), source_version=body.version)


@router.post("/{module_id}/reimport", status_code=202)
def reimport_module(
    module_id: uuid.UUID, request: Request, file: UploadFile = File(...), revision: int = Form(..., ge=1),
    db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin)),
    _: object = rate_limit(key_prefix="content_reimport", limit=10, window_seconds=60),
):
    from app.services.module_import_jobs import import_module_zip_job
    name, size, _ = _inspect_upload(file, max_bytes=1024 * 1024 * 1024)
    if pathlib.PurePath(name).suffix.lower() != ".zip":
        raise HTTPException(422, "Выберите ZIP-архив")
    import zipfile
    if not zipfile.is_zipfile(file.file):
        raise HTTPException(422, "Файл не является ZIP-архивом")
    file.file.seek(0)
    module = _editable(db, module_id, revision)
    title = module.title
    source_prefix = (module.storage_prefix or f"modules/{module_id}/").rstrip("/")
    db.rollback()  # Do not block learners while uploading or waiting for the queue.
    lock_key = f"content:import:{module_id}"
    job_id = uuid.uuid4().hex
    try:
        redis = get_redis()
        claimed = redis.set(lock_key, job_id, nx=True, ex=6 * 60 * 60)
        if not claimed:
            existing_id = redis.get(lock_key)
            existing_id = existing_id.decode() if isinstance(existing_id, bytes) else str(existing_id or "")
            existing_job = fetch_job(existing_id) if existing_id else None
            if existing_job and get_job_status(existing_job) in {"finished", "failed", "canceled", "stopped"}:
                release_job_lock(redis, lock_key, existing_id)
                claimed = redis.set(lock_key, job_id, nx=True, ex=6 * 60 * 60)
            if not claimed:
                if existing_job:
                    return {"ok": True, "job_id": existing_id, "module_id": str(module_id), "reused": True}
                raise HTTPException(409, "Обновление уже загружается в другой вкладке. Дождитесь завершения или повторите позже.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Очередь обновления временно недоступна") from exc
    object_key = f"{source_prefix}/_sources/{job_id}.zip"
    enqueued = False
    try:
        s3 = get_s3_client()
        upload_fileobj_with_retry(s3=s3, object_key=object_key, fileobj=file.file, content_type="application/zip", size_bytes=size)
        job = get_queue(str(settings.rq_queue_import)).enqueue(
            import_module_zip_job, job_id=job_id,
            meta={"job_kind": "import", "module_id": str(module_id), "module_title": title,
                  "reimport_existing": True, "expected_revision": revision, "actor_user_id": str(user.id), "import_object_key": object_key},
            s3_object_key=object_key, title=title, source_filename=name,
            actor_user_id=str(user.id), module_id=str(module_id), expected_revision=revision,
            force_reimport=True, enqueue_regen=False, reimport_existing=True,
            job_timeout=60 * 60 * 3, result_ttl=60 * 60 * 24 * 7, failure_ttl=60 * 60 * 24 * 7,
        )
        enqueued = True
        try:
            from datetime import datetime, timezone
            import json
            redis.lpush("admin:import_jobs", json.dumps({"job_id": job.id, "object_key": object_key,
                "title": title, "module_id": str(module_id), "module_title": title, "source_filename": name,
                "actor_user_id": str(user.id), "reimport_existing": True, "expected_revision": revision,
                "created_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
            redis.ltrim("admin:import_jobs", 0, 199)
        except Exception:
            pass
        audit_log(db=db, request=request, actor_user_id=user.id, event_type="content_reimport_enqueued",
                  meta={"module_id": str(module_id), "job_id": job.id, "revision": revision})
        db.commit()
        return {"ok": True, "job_id": str(job.id), "module_id": str(module_id)}
    except Exception as exc:
        if not enqueued:
            try:
                release_job_lock(redis, lock_key, job_id)
            except Exception:
                pass
            # Enqueue can succeed in Redis while its response is lost. Never
            # delete a source which an accepted worker may already be using.
            raise HTTPException(503, "Не удалось подтвердить запуск импорта. Проверьте модуль и журнал задач перед повтором.") from exc
        # Job is already accepted; metadata failure must not imply a failed upload.
        return {"ok": True, "job_id": str(job.id), "module_id": str(module_id)}


@router.get("/{module_id}/lessons/{lesson_id}/quiz")
def lesson_quiz(module_id: uuid.UUID, lesson_id: uuid.UUID, db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if module is None:
        raise HTTPException(404, "Модуль не найден")
    lesson = require_lesson(db, module, lesson_id)
    return quiz_payload(db, module, lesson)


@router.put("/{module_id}/lessons/{lesson_id}/quiz")
def save_lesson_quiz(module_id: uuid.UUID, lesson_id: uuid.UUID, body: QuizSave, request: Request,
                     db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin))):
    module = _editable(db, module_id, body.revision)
    lesson = require_lesson(db, module, lesson_id)
    if lesson.is_archived or lesson.is_folder:
        raise HTTPException(409, "Тест можно редактировать только у активного урока")
    previous = {q.id: q for q in db.scalars(select(Question).where(Question.quiz_id == lesson.quiz_id))}
    if any(q.id and q.id not in previous for q in body.questions):
        raise HTTPException(409, "Вопросы относятся к другой версии теста. Обновите редактор.")
    preserve_progress(db, module)
    remember_quiz_version(db, lesson)
    target = Quiz(type=QuizType.submodule, pass_threshold=body.pass_threshold,
                  time_limit=body.time_limit, attempts_limit=body.attempts_limit)
    db.add(target)
    db.flush()
    for index, q in enumerate(body.questions, 1):
        old = previous.get(q.id)
        db.add(Question(quiz_id=target.id, position=index, type=QuestionType(q.type), difficulty=old.difficulty if old else 1,
            prompt=format_prompt(q), correct_answer=",".join("ABCDE"[i] for i in sorted(q.correct)),
            explanation=q.explanation or None, concept_tag=old.concept_tag if old and not str(old.concept_tag or "").startswith("needs_regen:") else "author:reviewed",
            variant_group=old.variant_group if old else None))
    lesson.quiz_id, lesson.requires_quiz = target.id, body.enabled
    db.flush()
    remember_quiz_version(db, lesson)
    state = _finish(db, request, user, module, "content_quiz_saved", submodule_id=str(lesson.id), quiz_id=str(target.id), questions=len(body.questions))
    return {"workspace": state, "quiz": quiz_payload(db, module, lesson)}


@router.get("/{module_id}/final-quiz")
def final_quiz_settings(module_id: uuid.UUID, db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if not module:
        raise HTTPException(404, "Модуль не найден")
    quiz = db.get(Quiz, module.final_quiz_id) if module.final_quiz_id else None
    return {"revision": module.content_revision, "enabled": module.final_quiz_enabled and quiz is not None,
            "pass_threshold": quiz.pass_threshold if quiz else 70, "time_limit": quiz.time_limit if quiz else None,
            "attempts_limit": quiz.attempts_limit if quiz else 3,
            "source_lessons": db.scalar(select(func.count()).select_from(Submodule).where(Submodule.module_id == module.id,
                Submodule.is_archived.is_(False), Submodule.is_folder.is_(False), Submodule.requires_quiz.is_(True))) or 0}


@router.put("/{module_id}/final-quiz")
def save_final_quiz(module_id: uuid.UUID, body: FinalQuizSave, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(UserRole.admin))):
    module = _editable(db, module_id, body.revision)
    if body.enabled and not final_quiz_settings(module.id, db)["source_lessons"]:
        raise HTTPException(422, "Сначала включите хотя бы один тест урока: из них собирается итоговый тест")
    preserve_progress(db, module)
    quiz = db.get(Quiz, module.final_quiz_id) if module.final_quiz_id else None
    if not quiz:
        quiz = Quiz(type=QuizType.final)
        db.add(quiz)
        db.flush()
        module.final_quiz_id = quiz.id
    module.final_quiz_enabled = body.enabled
    quiz.pass_threshold, quiz.time_limit, quiz.attempts_limit = body.pass_threshold, body.time_limit, body.attempts_limit
    return _finish(db, request, user, module, "content_final_quiz_settings_saved")


def _draft_key(module_id, lesson_id):
    return f"authoring:draft:{module_id}:{lesson_id}"


@router.post("/{module_id}/lessons/{lesson_id}/quiz-draft", status_code=202)
def create_quiz_draft(module_id: uuid.UUID, lesson_id: uuid.UUID, body: GenerateDraft, request: Request,
                      db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin)),
                      _: object = rate_limit(key_prefix="quiz_draft", limit=10, window_seconds=60)):
    module = _editable(db, module_id, body.revision)
    lesson = require_lesson(db, module, lesson_id)
    if lesson.is_archived or lesson.is_folder:
        raise HTTPException(409, "Выберите активный урок")
    if not str(settings.openrouter_api_key or "").strip():
        raise HTTPException(503, "AI-провайдер не настроен. Добавьте вопросы вручную или настройте OPENROUTER_API_KEY на сервере.")
    fingerprint = source_revision(db, lesson)
    signature = request_signature(fingerprint, body.count, body.source_text)
    key = _draft_key(module.id, lesson.id)
    job_id = uuid.uuid4().hex
    try:
        redis = get_redis()
        old_id = redis.get(key)
        old = fetch_job(old_id.decode() if isinstance(old_id, bytes) else str(old_id), strict=True) if old_id else None
        if old and (old.meta or {}).get("request_signature") == signature and get_job_status(old) in {"queued", "started", "scheduled", "deferred"}:
            return {"id": str(old.id), "status": get_job_status(old), "existing": True}
        # Persist the known ID first: a lost enqueue reply must remain recoverable.
        redis.setex(key, 7 * 86400, job_id)
        job = get_queue(settings.rq_queue_regen).enqueue(generate_quiz_draft_job, str(module.id), str(lesson.id),
            module.content_revision, body.count, body.source_text, source_fingerprint=fingerprint, job_id=job_id, job_timeout=300,
            result_ttl=7 * 86400, failure_ttl=7 * 86400,
            meta={"job_kind": "quiz_draft", "module_id": str(module.id), "lesson_id": str(lesson.id),
                  "actor_user_id": str(user.id), "revision": module.content_revision, "source_revision": fingerprint, "request_signature": signature})
    except Exception as exc:
        raise HTTPException(503, "Не удалось подтвердить запуск AI. Действующие вопросы не изменены. Обновите статус перед повтором.") from exc
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="content_quiz_draft_requested",
              meta={"module_id": str(module.id), "submodule_id": str(lesson.id), "job_id": str(job.id)})
    db.commit()
    return {"id": str(job.id), "status": "queued"}


@router.get("/{module_id}/lessons/{lesson_id}/quiz-draft")
def get_quiz_draft(module_id: uuid.UUID, lesson_id: uuid.UUID, job_id: str | None = None, db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if not module:
        raise HTTPException(404, "Модуль не найден")
    lesson = require_lesson(db, module, lesson_id)
    if job_id is None:
        try:
            job_id = get_redis().get(_draft_key(module_id, lesson_id))
        except Exception as exc:
            raise HTTPException(503, "Не удалось получить статус черновика") from exc
    if not job_id:
        return {"id": None, "status": "none"}
    job_id = job_id.decode() if isinstance(job_id, bytes) else str(job_id)
    try:
        job = fetch_job(job_id, strict=True)
        status = get_job_status(job) if job else None
    except Exception as exc:
        raise HTTPException(503, "Статус AI временно недоступен. Это не означает, что черновик удалён; повторите проверку позже.") from exc
    if not job:
        return {"id": job_id, "status": "missing", "error": "Черновик не найден: запуск мог не завершиться или истёк срок хранения (7 дней). Создайте новый."}
    if (job.meta or {}).get("module_id") != str(module_id) or (job.meta or {}).get("lesson_id") != str(lesson_id) or (job.meta or {}).get("job_kind") != "quiz_draft":
        raise HTTPException(404, "Черновик этого урока не найден")
    try:
        result = job.result if status == "finished" else None
    except Exception as exc:
        raise HTTPException(503, "Результат AI временно недоступен. Повторите проверку позже.") from exc
    return {"id": str(job.id), "status": status, "result": result,
            "stale": module.is_archived or lesson.is_archived or ((job.meta or {}).get("source_revision") != source_revision(db, lesson) if (job.meta or {}).get("source_revision") else (job.meta or {}).get("revision") != module.content_revision),
            "error": "Обработчик прервал подготовку. Действующий тест не изменён." if status in {"failed", "stopped", "canceled"} else None}


@router.post("/{module_id}/quiz-drafts", status_code=202)
def create_module_quiz_drafts(module_id: uuid.UUID, body: GenerateModuleDrafts, request: Request,
                               db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.admin)),
                               _: object = rate_limit(key_prefix="module_quiz_drafts", limit=3, window_seconds=60)):
    module = _editable(db, module_id, body.revision)
    receipt = prepare_module_drafts(db, module, actor_id=user.id, count=body.count,
        only_missing=body.only_missing, lesson_ids=body.lesson_ids)
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="content_module_quiz_drafts_requested",
              meta={"module_id": str(module.id), "batch_id": receipt.get("id"), "lessons": len(receipt.get("items", []))})
    db.commit()
    if not receipt.get("id"):
        return receipt
    return {**receipt, "working": True, "counts": {"queued": len(receipt["items"])},
            "items": [{"lesson_id": item["lesson_id"], "title": item["title"], "status": "queued", "questions": 0,
                       "current_questions": 0, "required": False, "error": None} for item in receipt["items"]]}


@router.get("/{module_id}/quiz-drafts")
def get_module_quiz_drafts(module_id: uuid.UUID, batch_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if not module:
        raise HTTPException(404, "Модуль не найден")
    return module_draft_status(db, module, batch_id.hex if batch_id else None)
