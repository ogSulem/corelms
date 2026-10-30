from __future__ import annotations

import logging
import mimetypes
import uuid
from pathlib import PurePosixPath
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limit
from app.core.security import get_current_user, require_roles
from app.core.security_audit_log import audit_log
from app.db.session import get_db
from app.services.app_settings import get_platform_settings
from app.models.asset import AssetRevision, ContentAsset
from app.models.sales import SalesEntry
from app.models.user import User, UserRole
from app.routers.content import _inspect_upload
from app.schemas.content import VersionRestore
from app.services.content import safe_filename, snapshot_asset
from app.services.media import stage_rendition
from app.services.chunked_uploads import (append_chunk, checksum_and_size, chunk_size, create_session, discard,
    discard_blob, open_blob, read_result, read_session, require_free_space, save_result)
from app.services.sales_library import (adopt_legacy_page, clean_path, delete_subtree, get_section, identity, join_path,
    listing_payload, managed_key, move_subtree, path_is_visible, require_available_name, require_directory,
    require_entry)
from app.services.storage import effective_bucket, get_s3_client, upload_fileobj_with_retry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/sales-files", tags=["sales"])
Section = Literal["photos", "catalogs"]


class FolderCreate(BaseModel):
    section: Section
    path: str = ""
    name: str = Field(min_length=1, max_length=400)
    revision: int = Field(ge=1)


class EntryEdit(BaseModel):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=400)
    is_archived: bool | None = None


class EntryMove(BaseModel):
    revision: int = Field(ge=1)
    path: str = Field(default="", max_length=1000)


class EntryDelete(BaseModel):
    revision: int = Field(ge=1)


class SalesUploadStart(BaseModel):
    """Начало частичной загрузки файла продаж."""
    section: Section
    path: str = Field(default="", max_length=1000)
    revision: int = Field(ge=1)
    filename: str = Field(min_length=1, max_length=400)
    size_bytes: int = Field(ge=1, le=20 * 1024 * 1024 * 1024)
    replace_id: uuid.UUID | None = None


def finish(db: Session, request: Request, user: User, section, path: str, event: str, **meta):
    section.revision += 1
    audit_log(db=db, request=request, actor_user_id=user.id, event_type=event, meta={"section": section.name, **meta})
    db.commit()
    return listing_payload(db, section.name, path, include_archived=True)


@router.get("/list")
def list_sales_files(section: Section, path: str = "", include_archived: bool = False,
                     offset: int = Query(default=0, ge=0, le=1_000_000), q: str = Query(default="", max_length=200),
                     legacy_cursor: str | None = Query(default=None, max_length=4000),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user),
                     _: object = rate_limit(key_prefix="sales_files_list", limit=120, window_seconds=60)):
    path = clean_path(path)
    if include_archived and user.role != UserRole.superadmin:
        raise HTTPException(403, "Архив доступен только суперадминистратору")
    cursor, notice = adopt_legacy_page(db, section, path, cursor=legacy_cursor, include_archived=include_archived)
    return listing_payload(db, section, path, include_archived=include_archived, offset=offset,
                           query=q.strip(), legacy_cursor=cursor, notice=notice)


@router.post("/mkdir", status_code=201)
def create_folder(body: FolderCreate, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(UserRole.superadmin))):
    path, name = clean_path(body.path), safe_filename(body.name)
    join_path(path, name)
    get_section(db, body.section, revision=body.revision)
    require_directory(db, body.section, path)
    require_available_name(db, body.section, path, name, check_legacy=True)
    section = get_section(db, body.section, revision=body.revision, lock=True)
    require_directory(db, body.section, path)
    require_available_name(db, body.section, path, name)
    entry = SalesEntry(section=body.section, path=path, name=name, kind="folder",
                       identity_key=identity(body.section, path, name, "folder"))
    db.add(entry)
    db.flush()
    return finish(db, request, user, section, path, "sales_folder_created", entry_id=str(entry.id))


def _register_sales_file(db: Session, request: Request, user: User, *, section: str, path: str, revision: int | None,
                         filename: str, size: int, checksum: str, bucket: str, key: str, mime: str,
                         replace_id: uuid.UUID | None, progress: dict) -> dict:
    """Файл уже в S3: записываем каталог, версию и аудит. Общее для обычной и частичной загрузки."""
    entry = require_entry(db, replace_id) if replace_id else None
    name = str(PurePosixPath(entry.name).with_suffix(PurePosixPath(filename).suffix)) if entry else filename
    path = entry.path if entry else path
    root = get_section(db, section, revision=revision, lock=True)
    require_directory(db, section, path)
    require_available_name(db, section, path, name, exclude=entry.id if entry else None)
    entry = require_entry(db, replace_id) if replace_id else None
    if entry and (entry.section != section or entry.kind != "file" or entry.is_archived or entry.path != path):
        raise HTTPException(409, "Файл изменён. Обновите список.")
    if entry:
        asset = db.get(ContentAsset, entry.asset_id)
        snapshot_asset(db, asset)
        entry.name, entry.identity_key = name, identity(section, path, name)
        asset.original_filename = name
        asset.bucket, asset.object_key, asset.mime_type = bucket, key, mime
        asset.checksum_sha256, asset.size_bytes, asset.created_by = checksum, size, user.id
    else:
        asset = ContentAsset(bucket=bucket, object_key=key, original_filename=name, mime_type=mime,
                             size_bytes=size, checksum_sha256=checksum, created_by=user.id)
        db.add(asset)
        db.flush()
        entry = SalesEntry(section=section, path=path, name=name, kind="file", asset_id=asset.id,
                           identity_key=identity(section, path, name))
        db.add(entry)
    db.flush()
    stage_rendition(db, asset)
    root.revision += 1
    audit_log(db=db, request=request, actor_user_id=user.id, event_type="sales_file_replaced" if replace_id else "sales_file_uploaded",
              meta={"section": section, "entry_id": str(entry.id), "asset_id": str(asset.id), "version": asset.version})
    progress["committed"] = True
    db.commit()
    return listing_payload(db, section, path, include_archived=True)


def _sales_upload_target(db: Session, section: str, path: str, revision: int | None, filename: str,
                         replace_id: uuid.UUID | None) -> tuple[str, str]:
    path = clean_path(path)
    get_section(db, section, revision=revision)
    entry = require_entry(db, replace_id) if replace_id else None
    if entry and (entry.section != section or entry.kind != "file" or entry.is_archived):
        raise HTTPException(409, "Выберите активный файл этого раздела")
    name = str(PurePosixPath(entry.name).with_suffix(PurePosixPath(filename).suffix)) if entry else filename
    path = entry.path if entry else path
    require_directory(db, section, path)
    require_available_name(db, section, path, name, exclude=entry.id if entry else None,
                           check_legacy=not entry or name != entry.name)
    db.commit()
    return path, name


@router.post("/upload", status_code=201)
def upload_sales_file(request: Request, file: UploadFile = File(...), section: Section = Form(...),
                      path: str = Form(default=""), revision: int = Form(..., ge=1),
                      replace_id: uuid.UUID | None = Form(default=None), db: Session = Depends(get_db),
                      user: User = Depends(require_roles(UserRole.superadmin)),
                      _: object = rate_limit(key_prefix="sales_upload", limit=120, window_seconds=60)):
    filename, size, checksum = _inspect_upload(file, max_bytes=get_platform_settings(db).upload_max_bytes)
    path, _ = _sales_upload_target(db, section, path, revision, filename, replace_id)
    bucket, key = effective_bucket(), managed_key(section, filename)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    s3 = get_s3_client()
    progress: dict = {"committed": False}
    try:
        upload_fileobj_with_retry(s3=s3, object_key=key, fileobj=file.file, content_type=mime, size_bytes=size)
        return _register_sales_file(db, request, user, section=section, path=path, revision=revision,
            filename=filename, size=size, checksum=checksum, bucket=bucket, key=key, mime=mime,
            replace_id=replace_id, progress=progress)
    except Exception:
        db.rollback()
        if not progress["committed"]:
            try:
                s3.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass  # Delete only our unpublished staging object, never a prior version.
        raise


@router.post("/uploads", status_code=201)
def start_sales_upload(body: SalesUploadStart, db: Session = Depends(get_db),
                       user: User = Depends(require_roles(UserRole.superadmin))):
    """Большие фото и каталоги принимаем частями: один длинный запрос обрывают прокси."""
    limit = get_platform_settings(db).upload_max_bytes
    if body.size_bytes > limit:
        raise HTTPException(413, f"Файл больше лимита {limit // (1024 * 1024)} МБ. Лимит меняется в настройках платформы.")
    filename = safe_filename(body.filename)
    path, _ = _sales_upload_target(db, body.section, body.path, body.revision, filename, body.replace_id)
    require_free_space(body.size_bytes)
    session = create_session(user_id=str(user.id), kind="sales", filename=filename, size_bytes=body.size_bytes,
        meta={"section": body.section, "path": path, "revision": body.revision,
              "replace_id": str(body.replace_id) if body.replace_id else None})
    return {"upload_id": session.id, "chunk_size": chunk_size(), "offset": 0,
            "filename": filename, "size_bytes": session.size_bytes}


@router.put("/uploads/{upload_id}")
async def push_sales_chunk(upload_id: str, request: Request, offset: int = Query(default=0, ge=0),
                           user: User = Depends(require_roles(UserRole.superadmin))):
    session = read_session(upload_id)
    if session.kind != "sales" or session.user_id != str(user.id):
        raise HTTPException(404, "Загрузка не найдена. Начните её заново.")
    remaining = max(0, session.size_bytes - offset)
    total = await append_chunk(upload_id, offset=offset, stream=request.stream(),
                               limit=min(chunk_size() * 2, remaining) or chunk_size())
    if total > session.size_bytes:
        discard(upload_id)
        raise HTTPException(413, "Файл больше заявленного размера. Начните загрузку заново.")
    return {"upload_id": upload_id, "offset": total, "size_bytes": session.size_bytes}


@router.post("/uploads/{upload_id}/complete")
def complete_sales_upload(upload_id: str, request: Request, db: Session = Depends(get_db),
                          user: User = Depends(require_roles(UserRole.superadmin))):
    session = read_session(upload_id)
    if session.kind != "sales" or session.user_id != str(user.id):
        raise HTTPException(404, "Загрузка не найдена. Начните её заново.")
    previous = read_result(upload_id)
    if previous is not None:
        return previous
    checksum, size = checksum_and_size(upload_id)
    if size != session.size_bytes:
        raise HTTPException(409, f"Файл получен не полностью: {size} из {session.size_bytes} байт. "
                                 "Продолжите загрузку — уже отправленные куски сохранены.")
    meta = session.meta
    replace_id = uuid.UUID(meta["replace_id"]) if meta.get("replace_id") else None
    section = meta["section"]
    path, _ = _sales_upload_target(db, section, meta.get("path") or "", None, session.filename, replace_id)
    bucket, key = effective_bucket(), managed_key(section, session.filename)
    mime = mimetypes.guess_type(session.filename)[0] or "application/octet-stream"
    s3 = get_s3_client()
    progress: dict = {"committed": False}
    blob = open_blob(upload_id)
    try:
        upload_fileobj_with_retry(s3=s3, object_key=key, fileobj=blob, content_type=mime, size_bytes=size)
        state = _register_sales_file(db, request, user, section=section, path=path, revision=None,
            filename=session.filename, size=size, checksum=checksum, bucket=bucket, key=key, mime=mime,
            replace_id=replace_id, progress=progress)
    except Exception:
        db.rollback()
        if not progress["committed"]:
            try:
                s3.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass
        raise
    finally:
        blob.close()
    save_result(upload_id, state)
    discard_blob(upload_id)
    return state


@router.delete("/uploads/{upload_id}")
def cancel_sales_upload(upload_id: str, user: User = Depends(require_roles(UserRole.superadmin))):
    session = read_session(upload_id)
    if session.kind != "sales" or session.user_id != str(user.id):
        raise HTTPException(404, "Загрузка не найдена")
    discard(upload_id)
    return {"ok": True}


@router.patch("/entries/{entry_id}")
def edit_entry(entry_id: uuid.UUID, body: EntryEdit, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require_roles(UserRole.superadmin))):
    """Переименование файла или папки. Папку переименовываем вместе с содержимым."""
    entry = require_entry(db, entry_id)
    root = get_section(db, entry.section, revision=body.revision, lock=True)
    db.refresh(entry)
    if body.is_archived is False and not path_is_visible(db, entry.section, entry.path):
        raise HTTPException(409, "Сначала восстановите родительскую папку")
    if body.name is not None and body.name != entry.name:
        name = safe_filename(body.name)
        if entry.kind == "file" and PurePosixPath(name).suffix.lower() != PurePosixPath(entry.name).suffix.lower():
            raise HTTPException(422, "Чтобы изменить формат, используйте замену файла")
        # Нельзя переименовать так, чтобы «спрятать» необработанный файл старого хранилища.
        require_available_name(db, entry.section, entry.path, name, exclude=entry.id, check_legacy=True)
        move_subtree(db, entry, new_name=name)
    if body.is_archived is not None:
        entry.is_archived = body.is_archived
        if entry.asset_id:
            db.get(ContentAsset, entry.asset_id).is_archived = body.is_archived
    return finish(db, request, user, root, entry.path, "sales_entry_updated", entry_id=str(entry.id),
                  fields=sorted(body.model_fields_set - {"revision"}))


@router.post("/entries/{entry_id}/move")
def move_entry(entry_id: uuid.UUID, body: EntryMove, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require_roles(UserRole.superadmin))):
    """Перенос файла или папки в другую папку — как перетаскиванием в проводнике."""
    entry = require_entry(db, entry_id)
    root = get_section(db, entry.section, revision=body.revision, lock=True)
    db.refresh(entry)
    destination = clean_path(body.path)
    require_available_name(db, entry.section, destination, entry.name, exclude=entry.id, check_legacy=True)
    move_subtree(db, entry, destination=destination)
    return finish(db, request, user, root, entry.path, "sales_entry_moved", entry_id=str(entry.id),
                  destination=entry.path)


@router.post("/entries/{entry_id}/delete")
def delete_entry(entry_id: uuid.UUID, body: EntryDelete, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_roles(UserRole.superadmin))):
    """Удаление навсегда: только из архива и только для папки/файла без прочей истории.

    Архив остаётся обратимым, поэтому физическое удаление требует явного шага:
    сначала материал убирают в архив, затем удаляют окончательно.
    """
    entry = require_entry(db, entry_id)
    if not entry.is_archived:
        raise HTTPException(409, "Сначала переместите в архив — так материал можно вернуть.")
    root = get_section(db, entry.section, revision=body.revision, lock=True)
    db.refresh(entry)
    if entry.kind == "folder":
        active = db.scalar(select(SalesEntry.id).where(SalesEntry.section == entry.section,
            (SalesEntry.path == join_path(entry.path, entry.name)) | SalesEntry.path.startswith(join_path(entry.path, entry.name) + "/"),
            SalesEntry.is_archived.is_(False)).limit(1))
        if active:
            raise HTTPException(409, "В папке есть активные материалы. Сначала уберите их в архив.")
    keys = delete_subtree(db, entry)
    state = finish(db, request, user, root, entry.path, "sales_entry_deleted", entry_id=str(entry_id), kind=entry.kind)
    s3 = get_s3_client()
    for bucket, key in keys:
        try:
            s3.delete_object(Bucket=bucket, Key=key)
        except Exception:
            log.warning("sales delete: object cleanup failed", extra={"object_key": key})
    return state


@router.get("/entries/{entry_id}/versions")
def file_versions(entry_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.superadmin))):
    entry = require_entry(db, entry_id)
    if not entry.asset_id:
        raise HTTPException(422, "У папки нет версий файла")
    asset = db.get(ContentAsset, entry.asset_id)
    rows = list(db.scalars(select(AssetRevision).where(AssetRevision.asset_id == asset.id).order_by(AssetRevision.version.desc())))
    return {"current_version": asset.version, "items": [{"version": r.version, "filename": r.original_filename,
        "size_bytes": r.size_bytes, "created_at": r.created_at.isoformat()} for r in rows]}


@router.post("/entries/{entry_id}/restore-version")
def restore_version(entry_id: uuid.UUID, body: VersionRestore, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(UserRole.superadmin))):
    entry = require_entry(db, entry_id)
    get_section(db, entry.section, revision=body.revision)
    require_directory(db, entry.section, entry.path)
    if not entry.asset_id or entry.is_archived:
        raise HTTPException(409, "Сначала восстановите файл из архива")
    asset = db.get(ContentAsset, entry.asset_id)
    old = db.scalar(select(AssetRevision).where(AssetRevision.asset_id == asset.id, AssetRevision.version == body.version))
    if old is None:
        raise HTTPException(404, "Версия не найдена")
    try:
        get_s3_client().head_object(Bucket=old.bucket, Key=old.object_key)
    except Exception as exc:
        raise HTTPException(409, "Оригинал этой версии недоступен в хранилище") from exc
    name = str(PurePosixPath(entry.name).with_suffix(PurePosixPath(old.original_filename).suffix))
    require_available_name(db, entry.section, entry.path, name, exclude=entry.id, check_legacy=name != entry.name)
    root = get_section(db, entry.section, revision=body.revision, lock=True)
    db.refresh(entry)
    db.refresh(asset)
    require_directory(db, entry.section, entry.path)
    require_available_name(db, entry.section, entry.path, name, exclude=entry.id)
    snapshot_asset(db, asset)
    asset.bucket, asset.object_key, asset.mime_type = old.bucket, old.object_key, old.mime_type
    asset.size_bytes, asset.checksum_sha256, asset.original_filename = old.size_bytes, old.checksum_sha256, name
    asset.created_by = user.id
    entry.name, entry.identity_key = name, identity(entry.section, entry.path, name)
    db.flush()
    stage_rendition(db, asset)
    return finish(db, request, user, root, entry.path, "sales_file_version_restored", entry_id=str(entry.id), source_version=body.version)


# Old clients cannot overwrite objects with signed PUTs or physically delete prefixes.
@router.post("/presign-upload")
@router.get("/presign-download")
@router.delete("/object")
@router.delete("/folder")
def obsolete_sales_operation(user: User = Depends(require_roles(UserRole.superadmin))):
    raise HTTPException(410, "Обновите страницу продаж. Используйте защищённую загрузку, просмотр и обратимый архив.")
