"""Reversible sales folders over immutable ContentAssets, including legacy S3 files."""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import uuid
from pathlib import PurePosixPath

from botocore.exceptions import ClientError
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.asset import AssetRevision, ContentAsset
from app.models.media import AssetRendition, AssetThumb
from app.models.sales import SalesEntry, SalesSection
from app.services.content import normalize_name, safe_filename, serialize_asset
from app.services.storage import effective_bucket, get_s3_client
from app.services.thumbs import thumb_keys

log = logging.getLogger(__name__)


def clean_path(value: str | None) -> str:
    value = normalize_name(value or "")
    if not value:
        return ""
    if len(value.encode("utf-8")) > 1000 or "\\" in value or value.startswith("/") or value.endswith("/"):
        raise HTTPException(422, "Недопустимый путь папки")
    parts = value.split("/")
    if len(parts) > 20 or any(not p or p != safe_filename(p) for p in parts):
        raise HTTPException(422, "Недопустимый путь папки")
    return value


def join_path(path: str, name: str) -> str:
    return clean_path(f"{path}/{name}" if path else name)


def identity(section: str, path: str, name: str, kind: str = "file") -> str:
    return hashlib.sha256("\0".join((section, path, name, kind)).encode()).hexdigest()


def get_section(db: Session, section: str, *, revision: int | None = None, lock: bool = False) -> SalesSection:
    if section not in {"photos", "catalogs"}:
        raise HTTPException(422, "Неизвестный раздел продаж")
    if db.get(SalesSection, section) is None:
        try:
            with db.begin_nested():
                db.add(SalesSection(name=section))
                db.flush()
        except IntegrityError:
            pass  # Another first visitor registered the section.
    stmt = select(SalesSection).where(SalesSection.name == section).execution_options(populate_existing=True)
    row = db.scalar(stmt.with_for_update() if lock else stmt)
    if revision is not None and row.revision != revision:
        raise HTTPException(409, "Раздел изменён в другой вкладке. Обновите список перед повтором.")
    return row


def path_is_visible(db: Session, section: str, path: str) -> bool:
    parent = ""
    for name in clean_path(path).split("/") if path else []:
        row = db.scalar(select(SalesEntry).where(SalesEntry.identity_key == identity(section, parent, name, "folder")))
        if row is None or row.is_archived:
            return False
        parent = join_path(parent, name)
    return True


def require_directory(db: Session, section: str, path: str, *, allow_archived: bool = False):
    parent = ""
    for name in path.split("/") if path else []:
        row = db.scalar(select(SalesEntry).where(SalesEntry.identity_key == identity(section, parent, name, "folder")))
        if row is None or (row.is_archived and not allow_archived):
            raise HTTPException(404, "Папка недоступна. Откройте её через родительский каталог.")
        parent = join_path(parent, name)


def legacy_prefix(db: Session, section: str, path: str) -> str:
    if path:
        parent, _, name = path.rpartition("/")
        row = db.scalar(select(SalesEntry).where(SalesEntry.identity_key == identity(section, parent, name, "folder")))
        if row and row.legacy_key:
            return row.legacy_key.rstrip("/") + "/"
    return f"sales/{section}/{path + '/' if path else ''}"


def require_available_name(db: Session, section: str, path: str, name: str, *, exclude: uuid.UUID | None = None,
                           check_legacy: bool = False):
    rows = list(db.scalars(select(SalesEntry).where(SalesEntry.section == section, SalesEntry.path == path, SalesEntry.name == name)))
    if any(row.id != exclude for row in rows):
        raise HTTPException(409, "Это имя уже занято. Замените существующий файл или восстановите его из архива.")
    if check_legacy:
        # Unadopted legacy files must not be silently shadowed by a new upload.
        prefix = legacy_prefix(db, section, path)
        if len((prefix + name).encode("utf-8")) > 1024:
            return  # Such a legacy S3 object cannot exist; managed keys are short UUIDs.
        s3 = get_s3_client()
        try:
            s3.head_object(Bucket=effective_bucket(), Key=prefix + name)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"NoSuchKey", "NotFound", "404"}:
                raise HTTPException(503, "Не удалось проверить хранилище. Изменения не сохранены.") from exc
        except Exception as exc:
            raise HTTPException(503, "Не удалось проверить хранилище. Изменения не сохранены.") from exc
        else:
            raise HTTPException(409, "Файл уже есть в старом хранилище. Обновите список и используйте замену.")
        try:
            result = s3.list_objects_v2(Bucket=effective_bucket(), Prefix=prefix + name + "/", MaxKeys=1)
            if result.get("Contents") or result.get("CommonPrefixes"):
                raise HTTPException(409, "Папка с таким именем уже существует. Обновите список.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, "Не удалось проверить хранилище. Повторите позже.") from exc


def adopt_legacy_page(db: Session, section: str, path: str, *, cursor: str | None = None, include_archived: bool = False) -> tuple[str | None, str | None]:
    """One bounded listing; never move, overwrite or delete original object keys."""
    get_section(db, section)
    require_directory(db, section, path, allow_archived=include_archived)
    prefix = legacy_prefix(db, section, path)
    db.commit()  # No database lock during the storage request.
    bucket = effective_bucket()
    try:
        args = dict(Bucket=bucket, Prefix=prefix, Delimiter="/", MaxKeys=500)
        if cursor:
            args["ContinuationToken"] = cursor
        listing = get_s3_client().list_objects_v2(**args)
    except Exception:
        log.warning("Sales legacy listing unavailable for %s/%s", section, path, exc_info=True)
        return cursor, "Не удалось обновить старое хранилище. Показаны ранее зарегистрированные файлы."
    candidates = []
    for item in listing.get("CommonPrefixes", []):
        key = str(item.get("Prefix") or "")
        candidates.append((key, "folder", None))
    for item in listing.get("Contents", []):
        key = str(item.get("Key") or "")
        if key.endswith("/") or key.endswith("/.keep"):
            continue
        candidates.append((key, "file", int(item.get("Size") or 0)))
    records = []
    skipped = 0
    for key, kind, size in candidates[:500]:
        if not key.startswith(prefix):
            continue
        tail = key[len(prefix):].rstrip("/")
        try:
            name = safe_filename(tail)
            join_path(path, name)  # Bound cumulative path, not just each segment.
        except HTTPException:
            skipped += 1
            continue
        records.append((key, kind, size, name, identity(section, path, name, kind)))
    root = get_section(db, section, lock=True)
    require_directory(db, section, path, allow_archived=include_archived)
    known = set(db.scalars(select(SalesEntry.identity_key).where(SalesEntry.identity_key.in_([r[4] for r in records]))))
    keys = [r[0] for r in records]
    known_legacy = set(db.scalars(select(SalesEntry.legacy_key).where(SalesEntry.legacy_key.in_(keys))))
    assets = {a.object_key: a for a in db.scalars(select(ContentAsset).where(ContentAsset.object_key.in_(keys)))}
    changed = False
    for key, kind, size, name, digest in records:
        if digest in known or key in known_legacy:
            continue  # An archived/renamed/replaced legacy entry must never reappear.
        asset = None
        if kind == "file":
            if key in assets:
                # Never adopt an object already owned by a course or another sales entry.
                skipped += 1
                continue
            asset = ContentAsset(bucket=bucket, object_key=key, original_filename=name, size_bytes=size,
                                 mime_type=mimetypes.guess_type(name)[0] or "application/octet-stream")
            db.add(asset)
            db.flush()
        db.add(SalesEntry(section=section, path=path, name=name, kind=kind, identity_key=digest,
                          asset_id=asset.id if asset else None, legacy_key=key))
        known.add(digest)
        changed = True
    if changed:
        root.revision += 1
    db.commit()
    notice = f"Не показано записей с неподдерживаемыми или конфликтующими путями: {skipped}. Оригиналы не изменены." if skipped else None
    return listing.get("NextContinuationToken") if listing.get("IsTruncated") else None, notice


def listing_payload(db: Session, section: str, path: str, *, include_archived: bool = False, offset: int = 0,
                    query: str = "", legacy_cursor: str | None = None, notice: str | None = None) -> dict:
    root = get_section(db, section)
    require_directory(db, section, path, allow_archived=include_archived)
    stmt = select(SalesEntry).where(SalesEntry.section == section, SalesEntry.path == path)
    if not include_archived:
        stmt = stmt.where(SalesEntry.is_archived.is_(False))
    if query:
        stmt = stmt.where(func.lower(SalesEntry.name).contains(query.lower(), autoescape=True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    entries = list(db.scalars(stmt.order_by(SalesEntry.kind.desc(), SalesEntry.name, SalesEntry.id).offset(offset).limit(100)))
    assets = {a.id: a for a in db.scalars(select(ContentAsset).where(ContentAsset.id.in_([e.asset_id for e in entries if e.asset_id])))}
    counts = dict(db.execute(select(SalesEntry.path, func.count()).where(
        SalesEntry.section == section, SalesEntry.path.in_([join_path(path, e.name) for e in entries if e.kind == "folder"]),
        SalesEntry.is_archived.is_(False)).group_by(SalesEntry.path)).all())
    from app.services.app_settings import get_platform_settings
    return {"section": section, "path": path, "revision": root.revision, "total": total, "offset": offset,
        "upload_max_bytes": get_platform_settings(db).upload_max_bytes,
        "folder_counts": {join_path(path, e.name): counts.get(join_path(path, e.name), 0) for e in entries if e.kind == "folder"},
        "next_offset": offset + 100 if offset + 100 < total else None, "legacy_cursor": legacy_cursor, "notice": notice,
        "path_archived": not path_is_visible(db, section, path),
        "entries": [{"id": str(e.id), "kind": e.kind, "name": e.name, "path": join_path(e.path, e.name),
                     "is_archived": e.is_archived, "asset": serialize_asset(assets[e.asset_id]) if e.asset_id in assets else None} for e in entries]}


def subtree(db: Session, entry: SalesEntry) -> list[SalesEntry]:
    """Папка вместе со всем содержимым: перенос и удаление идут по всему дереву."""
    if entry.kind != "folder":
        return [entry]
    full = join_path(entry.path, entry.name)
    rows = list(db.scalars(select(SalesEntry).where(
        SalesEntry.section == entry.section,
        (SalesEntry.path == full) | SalesEntry.path.startswith(full + "/"))))
    return [entry, *[row for row in rows if row.id != entry.id]]


def move_subtree(db: Session, entry: SalesEntry, *, destination: str | None = None, new_name: str | None = None) -> None:
    """Переносит файл или папку с содержимым в другую папку (или переименовывает).

    Оригиналы в хранилище не трогаем: меняется только адрес записи в каталоге.
    """
    section = entry.section
    name = safe_filename(new_name) if new_name is not None else entry.name
    target_parent = entry.path if destination is None else clean_path(destination)
    if entry.kind == "folder":
        own = join_path(entry.path, entry.name)
        if target_parent == own or target_parent.startswith(own + "/"):
            raise HTTPException(422, "Нельзя переместить папку внутрь самой себя")
    if target_parent == entry.path and name == entry.name:
        return
    require_directory(db, section, target_parent)
    rows = subtree(db, entry)
    old_prefix = join_path(entry.path, entry.name) if entry.kind == "folder" else ""
    new_prefix = join_path(target_parent, name) if entry.kind == "folder" else ""
    plan: list[tuple[SalesEntry, str, str]] = []
    for row in rows:
        if row.id == entry.id:
            path, row_name = target_parent, name
        else:
            tail = row.path[len(old_prefix):].lstrip("/")
            path, row_name = (join_path(new_prefix, tail) if tail else new_prefix), row.name
        if path == row.path and row_name == row.name:
            continue
        plan.append((row, path, row_name))
    for row, path, row_name in plan:
        digest = identity(section, path, row_name, row.kind)
        clash = db.scalar(select(SalesEntry.id).where(SalesEntry.identity_key == digest))
        if clash and clash != row.id:
            raise HTTPException(409, f"В папке уже есть «{row_name}». Переименуйте объект или выберите другую папку.")
    for row, path, row_name in plan:
        row.path, row.name = path, row_name
        row.identity_key = identity(section, path, row_name, row.kind)
    db.flush()


def delete_subtree(db: Session, entry: SalesEntry) -> list[tuple[str, str]]:
    """Удаляет записи дерева и возвращает объекты хранилища к удалению после коммита.

    Сначала записи каталога, потом сами файлы: ссылка sales_entries.asset_id
    не даст удалить файл, пока на него смотрит запись.
    """
    rows = subtree(db, entry)
    keys: list[tuple[str, str]] = []
    assets: list[ContentAsset] = []
    for row in rows:
        asset = db.get(ContentAsset, row.asset_id) if row.asset_id else None
        if asset is not None:
            assets.append(asset)
            keys.append((asset.bucket, asset.object_key))
            for revision in db.scalars(select(AssetRevision).where(AssetRevision.asset_id == asset.id)):
                keys.append((revision.bucket, revision.object_key))
            for rendition in db.scalars(select(AssetRendition).where(AssetRendition.asset_id == asset.id)):
                if rendition.object_key:
                    keys.append((rendition.bucket, rendition.object_key))
            keys.extend(thumb_keys(db, asset.id))
        db.delete(row)
    db.flush()
    for asset in assets:
        db.execute(delete(AssetThumb).where(AssetThumb.asset_id == asset.id))
        db.execute(delete(AssetRendition).where(AssetRendition.asset_id == asset.id))
        db.execute(delete(AssetRevision).where(AssetRevision.asset_id == asset.id))
        db.delete(asset)
    db.flush()
    return keys


def require_entry(db: Session, entry_id: uuid.UUID) -> SalesEntry:
    entry = db.get(SalesEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "Файл или папка не найдены")
    return entry


def managed_key(section: str, name: str) -> str:
    suffix = PurePosixPath(name).suffix.lower()
    suffix = suffix if suffix.isascii() and len(suffix) <= 16 else ""
    return f"managed/sales/{section}/{uuid.uuid4().hex}{suffix}"
