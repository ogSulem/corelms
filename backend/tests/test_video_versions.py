"""Compatibility of historical converted files and retirement of the old writer."""
import hashlib

import pytest
from sqlalchemy import func, select

from app.models.asset import AssetRevision, ContentAsset
from app.models.module import Module
from app.models.submodule_asset import SubmoduleAssetMap
from app.services.content import snapshot_asset
from app.services.video_transcode_jobs import transcode_all_videos_job


@pytest.fixture()
def video(db, make_module, storage):
    module, lesson, _ = make_module()
    asset = ContentAsset(module_id=module.id, bucket="recorded-old-bucket", object_key="legacy/clip.mov",
        original_filename="Каталог/Обзор.mov", mime_type="video/quicktime", size_bytes=5,
        checksum_sha256=hashlib.sha256(b"input").hexdigest(), source_path="clip.mov",
        source_checksum_sha256=hashlib.sha256(b"input").hexdigest())
    db.add(asset); db.flush()
    db.add(SubmoduleAssetMap(submodule_id=lesson.id, asset_id=asset.id, order=1)); db.commit()
    storage.objects[asset.object_key] = b"input"
    return module, lesson, asset


@pytest.mark.parametrize('delete_original', [True, False])
def test_old_bulk_writer_cannot_overwrite_originals_even_when_resuming_queued_jobs(db, video, storage, delete_original):
    module, _, asset = video
    with pytest.raises(RuntimeError, match="замена видео отключена"):
        transcode_all_videos_job(delete_original=delete_original, after_asset_id=str(asset.id))
    db.expire_all()
    assert db.get(ContentAsset, asset.id).version == 1 and db.get(Module, module.id).content_revision == 1
    assert not storage.deleted and not storage.uploaded


def test_historical_cross_format_restore_keeps_name_but_uses_real_original_extension(client, db, video, admin_headers, storage):
    module, _, asset = video
    # Simulate a historical conversion made before the separate-rendition pipeline.
    snapshot_asset(db, asset)
    asset.object_key = 'old-browser.mp4'
    asset.original_filename = 'Каталог/Переименовано.mp4'
    asset.mime_type = 'video/mp4'
    asset.checksum_sha256 = hashlib.sha256(b'old converted video').hexdigest()
    asset.size_bytes = len(b'old converted video')
    db.commit(); storage.objects[asset.object_key] = b'old converted video'
    response = client.post(f'/admin/content/modules/{module.id}/assets/{asset.id}/restore-version', headers=admin_headers,
                           json={'version': 1, 'revision': module.content_revision})
    assert response.status_code == 200, response.text
    output = response.json()['assets'][0]
    assert output['original_filename'] == 'Каталог/Переименовано.mov'
    assert output['mime_type'] == 'video/quicktime' and output['version'] == 3
    assert db.scalar(select(func.count()).select_from(AssetRevision).where(AssetRevision.asset_id == asset.id)) == 2
    assert client.get(f'/assets/{asset.id}/download', headers=admin_headers).content == b'input'
    assert storage.objects['old-browser.mp4'] == b'old converted video' and not storage.deleted


def test_old_bulk_route_is_explicitly_retired(client, admin_headers):
    assert client.post('/admin/transcode/videos/enqueue', headers=admin_headers).status_code == 410
