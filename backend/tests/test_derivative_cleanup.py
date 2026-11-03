"""Производные файлы (браузерные копии и превью) не должны копиться при замене.

Замена файла поднимает версию оригинала. Пока уборки не было, каждая замена
видео оставляла в хранилище предыдущую копию mp4 и кадр — навсегда. Здесь
проверяется правило: держим текущую версию и одну предыдущую (для мгновенного
восстановления), всё более старое удаляем; оригиналы и история не страдают.
"""

import uuid

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.asset import ContentAsset
from app.models.media import AssetRendition, AssetThumb
from app.services.media import cleanup_superseded_derivatives


def _asset(db, module_id):
    asset = ContentAsset(module_id=module_id, bucket="testing",
                         object_key=f"modules/{module_id}/_versions/{uuid.uuid4().hex}.mp4",
                         original_filename="Видео.mp4", mime_type="video/mp4", version=4)
    db.add(asset)
    db.commit()
    return asset


def _derivative(db, model, asset, version, storage, *, state="ready"):
    key = f"derived/{asset.id}/{model.__name__}/{version}.bin"
    storage.objects[key] = b"derived"
    row = model(asset_id=asset.id, source_version=version, source_bucket=asset.bucket,
                source_object_key=f"orig-{version}", bucket="testing", object_key=key, state=state)
    if model is AssetRendition:
        row.mime_type = "video/mp4"
    db.add(row)
    db.commit()
    return row


def test_cleanup_keeps_current_and_one_previous_version(db, make_module, storage):
    module, _, _ = make_module()
    asset = _asset(db, module.id)
    renditions = {version: _derivative(db, AssetRendition, asset, version, storage) for version in (1, 2, 3)}
    thumbs = {version: _derivative(db, AssetThumb, asset, version, storage) for version in (1, 2, 3)}
    # У текущей версии тоже есть копия — её уборка не касается.
    current = _derivative(db, AssetRendition, asset, 4, storage)

    keys = {version: (renditions[version].object_key, thumbs[version].object_key) for version in (1, 2, 3)}
    current_key = current.object_key
    result = cleanup_superseded_derivatives([asset.id])
    assert result == {"rows": 4, "objects": 4}, result

    versions = sorted(db.scalars(select(AssetRendition.source_version).where(AssetRendition.asset_id == asset.id)))
    assert versions == [3, 4], versions
    assert sorted(db.scalars(select(AssetThumb.source_version).where(AssetThumb.asset_id == asset.id))) == [3]
    for version in (1, 2):
        for key in keys[version]:
            assert storage.objects.get(key) is None, "объект производного файла остался в S3"
    for key in keys[3]:
        assert storage.objects.get(key) is not None
    assert storage.objects.get(current_key) is not None


def test_cleanup_ignores_in_progress_versions(db, make_module, storage):
    """Копия, которую прямо сейчас готовит воркер, не удаляется у него из-под рук."""
    module, _, _ = make_module()
    asset = _asset(db, module.id)
    _derivative(db, AssetRendition, asset, 1, storage)
    processing = _derivative(db, AssetRendition, asset, 2, storage, state="processing")
    cleanup_superseded_derivatives([asset.id])
    # Версия 2 — самая свежая из предыдущих, поэтому остаётся в любом случае.
    assert storage.objects.get(processing.object_key) is not None
    assert db.get(AssetRendition, processing.id) is not None


def test_cleanup_never_touches_originals_or_asset_rows(db, make_module, storage):
    module, _, _ = make_module()
    asset = _asset(db, module.id)
    storage.objects[asset.object_key] = b"original"
    _derivative(db, AssetRendition, asset, 1, storage)
    _derivative(db, AssetRendition, asset, 2, storage)
    cleanup_superseded_derivatives([asset.id])
    assert storage.objects[asset.object_key] == b"original"
    assert db.get(ContentAsset, asset.id) is not None
    assert db.scalar(select(func.count()).select_from(ContentAsset).where(ContentAsset.id == asset.id)) == 1


def test_cleanup_is_noop_for_unknown_ids(storage):
    assert cleanup_superseded_derivatives([]) == {"rows": 0, "objects": 0}
    assert cleanup_superseded_derivatives([uuid.uuid4()]) == {"rows": 0, "objects": 0}
    assert storage.deleted == []
