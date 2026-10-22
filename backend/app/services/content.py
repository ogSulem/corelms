"""Transactional content lifecycle primitives shared by the editor and importer."""
from __future__ import annotations

import pathlib
import unicodedata
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.media import AssetRendition
from app.models.tag import ModuleTagMap
from app.models.asset import AssetRevision, ContentAsset
from app.models.module import Module, Submodule
from app.models.lesson_revision import LessonRevision
from app.models.submodule_asset import SubmoduleAssetMap
from app.services.learning import LearningService


def normalize_name(value: str) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip()


def safe_filename(value: str) -> str:
    value = normalize_name(value)
    if (not value or value in {".", ".."} or len(value) > 400
            or any(ord(c) < 32 or ord(c) == 127 for c in value) or "/" in value or "\\" in value):
        raise HTTPException(422, "Укажите имя файла без пути, до 400 символов")
    return value


def storage_key(module: Module, filename: str) -> str:
    # Object identity is unrelated to display name, ordering or Unicode URL encoding.
    suffix = pathlib.PurePath(filename).suffix.lower()
    suffix = suffix if suffix.isascii() and len(suffix) <= 16 else ""
    prefix = (module.storage_prefix or f"modules/{module.id}/").rstrip("/")
    return f"{prefix}/_versions/{uuid.uuid4().hex}{suffix}"


def lock_module(db: Session, module_id: uuid.UUID, expected_revision: int | None = None) -> Module:
    module = db.scalar(select(Module).where(Module.id == module_id).with_for_update().execution_options(populate_existing=True))
    if module is None:
        raise HTTPException(404, "Модуль не найден")
    if expected_revision is not None and module.content_revision != expected_revision:
        raise HTTPException(409, {
            "error_code": "content_conflict",
            "error_message": "Модуль уже изменён в другой вкладке или другим администратором. Обновите данные и повторите действие.",
        })
    return module


def preserve_progress(db: Session, module: Module) -> None:
    LearningService(db).remember_completions(module)


def snapshot_asset(db: Session, asset: ContentAsset) -> None:
    exists = db.scalar(select(AssetRevision.id).where(AssetRevision.asset_id == asset.id, AssetRevision.version == asset.version))
    if exists is None:
        db.add(AssetRevision(
            asset_id=asset.id, version=asset.version, bucket=asset.bucket,
            object_key=asset.object_key, original_filename=asset.original_filename,
            mime_type=asset.mime_type, size_bytes=asset.size_bytes, checksum_sha256=asset.checksum_sha256,
            created_at=asset.created_at, created_by=asset.created_by,
        ))
    asset.version += 1
    asset.created_at = datetime.now(timezone.utc)




def read_lesson_text(content: str | None, object_key: str | None, bucket: str | None = None) -> str:
    if not object_key or str(content or "").strip():
        return content or ""
    from app.services.storage import get_s3_client, effective_bucket
    try:
        body = get_s3_client().get_object(Bucket=bucket or effective_bucket(), Key=object_key)["Body"]
        try:
            raw = body.read(2 * 1024 * 1024 + 1)
        finally:
            body.close()
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("legacy text exceeds preview limit")
        return raw.decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(409, "Текст недоступен в хранилище. Повторите загрузку или обратитесь к администратору.") from exc


def snapshot_lesson(db: Session, lesson: Submodule, *, user_id: uuid.UUID | None = None) -> None:
    from app.services.storage import effective_bucket
    exists = db.scalar(select(LessonRevision.id).where(LessonRevision.submodule_id == lesson.id,
                                                      LessonRevision.version == lesson.content_version))
    if exists is None:
        db.add(LessonRevision(submodule_id=lesson.id, version=lesson.content_version,
            content=lesson.content or "", content_mode=lesson.content_mode,
            content_object_key=lesson.content_object_key,
            bucket=effective_bucket() if lesson.content_object_key else None, created_by=user_id))
    lesson.content_version += 1


def module_assets(db: Session, module_id: uuid.UUID) -> list[ContentAsset]:
    linked = select(SubmoduleAssetMap.asset_id).join(Submodule, Submodule.id == SubmoduleAssetMap.submodule_id).where(Submodule.module_id == module_id)
    return list(db.scalars(select(ContentAsset).where(or_(ContentAsset.module_id == module_id, ContentAsset.id.in_(linked))).order_by(ContentAsset.order, ContentAsset.original_filename)))


def require_owned_asset(db: Session, module: Module, asset_id: uuid.UUID) -> ContentAsset:
    asset = db.get(ContentAsset, asset_id)
    if asset is None:
        raise HTTPException(404, "Файл не найден")
    from app.models.sales import SalesEntry
    if db.scalar(select(SalesEntry.id).where(SalesEntry.asset_id == asset.id)):
        raise HTTPException(404, "Файл не принадлежит этому модулю")
    module_ids = set(db.scalars(select(Submodule.module_id).join(SubmoduleAssetMap, SubmoduleAssetMap.submodule_id == Submodule.id).where(SubmoduleAssetMap.asset_id == asset.id)))
    if asset.module_id:
        module_ids.add(asset.module_id)
    if module_ids != {module.id}:
        raise HTTPException(409 if module.id in module_ids else 404, "Файл не принадлежит только этому модулю. Загрузите отдельную копию.")
    asset.module_id = module.id
    return asset


def require_lesson(db: Session, module: Module, lesson_id: uuid.UUID) -> Submodule:
    sub = db.get(Submodule, lesson_id)
    if sub is None or sub.module_id != module.id:
        raise HTTPException(404, "Урок не найден в этом модуле")
    return sub


def ensure_filename_available(db: Session, module: Module, filename: str, submodule_id: uuid.UUID | None, *, exclude: uuid.UUID | None = None) -> None:
    assets = module_assets(db, module.id)
    links = dict(db.execute(select(SubmoduleAssetMap.asset_id, SubmoduleAssetMap.submodule_id).where(SubmoduleAssetMap.asset_id.in_([a.id for a in assets]))).all())
    for asset in assets:
        if asset.id == exclude or asset.is_archived or links.get(asset.id) != submodule_id:
            continue
        if normalize_name(asset.original_filename).casefold() == filename.casefold():
            raise HTTPException(409, "Файл с таким именем уже есть здесь. Используйте «Заменить» или выберите другое имя.")


def next_lesson_order(db: Session, module: Module) -> int:
    return int(db.scalar(select(func.max(Submodule.order)).where(Submodule.module_id == module.id)) or 0) + 1


def reorder_lessons(db: Session, module: Module, ordered: list[uuid.UUID]) -> None:
    all_subs = list(db.scalars(select(Submodule).where(Submodule.module_id == module.id).order_by(Submodule.order)))
    active = [s for s in all_subs if not s.is_archived]
    if len(ordered) != len(set(ordered)) or set(ordered) != {s.id for s in active}:
        raise HTTPException(422, "Передайте все активные уроки ровно один раз")
    by_id = {s.id: s for s in all_subs}
    # Unique(module_id, order) is immediate in PostgreSQL. Use a disjoint range
    # before final numbering; a CASE swap can still violate that constraint.
    start = min([s.order for s in all_subs] + [0]) - len(all_subs) - 1
    for index, sub in enumerate(all_subs):
        sub.order = start + index
    db.flush()
    full = [by_id[sid] for sid in ordered] + [s for s in all_subs if s.is_archived]
    for index, sub in enumerate(full, 1):
        sub.order = index
    db.flush()


def serialize_asset(asset: ContentAsset, *, submodule_id: uuid.UUID | None = None) -> dict:
    return {
        "asset_id": str(asset.id), "original_filename": asset.original_filename,
        "mime_type": asset.mime_type, "size_bytes": asset.size_bytes,
        "version": asset.version, "is_archived": asset.is_archived,
        "order": asset.order, "source_path": asset.source_path,
        "submodule_id": str(submodule_id) if submodule_id else None,
        "created_at": asset.created_at.isoformat(),
    }


def workspace(db: Session, module: Module) -> dict:
    subs = list(db.scalars(select(Submodule).where(Submodule.module_id == module.id).order_by(Submodule.order)))
    assets = module_assets(db, module.id)
    links = dict(db.execute(select(SubmoduleAssetMap.asset_id, SubmoduleAssetMap.submodule_id).where(SubmoduleAssetMap.submodule_id.in_([s.id for s in subs]))).all())
    return {
        "module": {
            "id": str(module.id), "title": module.title, "description": module.description,
            "category": module.category, "difficulty": module.difficulty,
            "is_active": module.is_active, "is_archived": module.is_archived,
            "final_quiz_id": str(module.final_quiz_id) if module.final_quiz_id else None,
            "final_quiz_enabled": module.final_quiz_enabled,
            "tag_ids": [str(t) for t in db.scalars(select(ModuleTagMap.tag_id).where(ModuleTagMap.module_id == module.id))],
            "visibility": module.visibility, "content_revision": module.content_revision,
            "import_object_key": module.import_object_key,
        },
        "lessons": [{
            "id": str(s.id), "title": s.title, "content": (s.content or "")[:4000],
            "content_length": len(s.content) if s.content else None,
            "presentation_mode": s.presentation_mode, "primary_asset_id": str(s.primary_asset_id) if s.primary_asset_id else None,
            "content_mode": s.content_mode, "content_version": s.content_version,
            "has_external_content": len(s.content or "") > 4000 or bool(s.content_object_key and not str(s.content or "").strip()),
            "order": s.order, "is_folder": s.is_folder, "is_archived": s.is_archived,
            "requires_quiz": s.requires_quiz, "quiz_id": str(s.quiz_id),
            "outline_path": s.outline_path, "source_path": s.source_path,
        } for s in subs],
        "assets": [serialize_asset(a, submodule_id=links.get(a.id)) for a in assets],
    }


def referenced_storage_keys(db: Session) -> set[str]:
    """Authoritative retention set, including archived materials and old versions."""
    keys = set(db.scalars(select(ContentAsset.object_key)))
    keys.update(db.scalars(select(AssetRevision.object_key)))
    keys.update(db.scalars(select(AssetRendition.object_key).where(AssetRendition.object_key.is_not(None))))
    keys.update(db.scalars(select(LessonRevision.content_object_key).where(LessonRevision.content_object_key.is_not(None))))
    keys.update(db.scalars(select(Module.import_object_key).where(Module.import_object_key.is_not(None))))
    keys.update(db.scalars(select(Submodule.content_object_key).where(Submodule.content_object_key.is_not(None))))
    return keys


def require_unused_temporary_object(db: Session, object_key: str) -> None:
    from app.core.redis_client import get_redis
    import json
    if not object_key.startswith("uploads/") or object_key.startswith("uploads/quickstart/"):
        raise HTTPException(409, "Удалять можно только временные загрузки, не материалы обучения")
    if object_key.lower().endswith(".zip"):
        raise HTTPException(409, "Исходные ZIP сохраняются для восстановления и повторного импорта. Физическое удаление отключено.")
    if object_key in referenced_storage_keys(db):
        raise HTTPException(409, "Файл используется модулем или историей версий. Используйте архив в редакторе.")
    try:
        redis = get_redis()
        if redis.get(f"admin:import_enqueued_by_object_key:{object_key}"):
            raise HTTPException(409, "Файл используется задачей импорта")
        for raw in redis.lrange("admin:import_jobs", 0, 500):
            try:
                entry = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if isinstance(entry, dict) and entry.get("object_key") == object_key:
                raise HTTPException(409, "Файл находится в журнале задач импорта. Удаление заблокировано.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Нельзя проверить очередь импорта. Файл не удалён.") from exc
