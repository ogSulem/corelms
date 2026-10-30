"""Превью файлов и быстрый путь подготовки видео.

Проверяем без ffmpeg: подменяем бинарник скриптом, который отдаёт готовый JPEG.
Так тест подтверждает именно нашу логику (клейм, ключ в S3, отдача, кэш),
а не сборку ffmpeg в песочнице.
"""
from __future__ import annotations

import pathlib
import stat
import sys
import uuid

import pytest

from app.core.config import settings
from app.models.asset import ContentAsset
from app.models.media import AssetThumb
from app.services import media, thumbs

MINIMAL_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300"
    + "10" * 64
    + "ffc00011080010001003011100021101031101"
    + "ffc4001f0000010501010101010100000000000000000102030405060708090a0b"
    + "ffda0008010100003f00d2cf20ffd9"
)


@pytest.fixture()
def fake_ffmpeg(tmp_path, monkeypatch):
    script = tmp_path / "ffmpeg"
    script.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.buffer.write({MINIMAL_JPEG!r})\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(settings, "ffmpeg_binary", str(script))
    return script


@pytest.fixture()
def broken_ffmpeg(tmp_path, monkeypatch):
    script = tmp_path / "ffmpeg-broken"
    script.write_text(f"#!{sys.executable}\nimport sys\nsys.stderr.write('no frame'); sys.exit(1)\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(settings, "ffmpeg_binary", str(script))
    return script


def _asset(db, *, filename="photo.jpg", payload=b"\xff\xd8original", version=1):
    asset = ContentAsset(bucket="testing", object_key=f"modules/{uuid.uuid4().hex}/{filename}",
                         original_filename=filename, mime_type="image/jpeg", size_bytes=len(payload), version=version)
    db.add(asset)
    db.commit()
    return asset


def test_thumb_kind_matches_previewable_formats():
    assert thumbs.thumb_kind("a.JPG") == "image"
    assert thumbs.thumb_kind("видео.mp4") == "video"
    assert thumbs.thumb_kind("план.mov") == "video"
    assert thumbs.thumb_kind("документ.pdf") is None
    assert thumbs.thumb_kind("архив.zip") is None
    assert thumbs.thumb_kind(None) is None


def test_faststart_prefix_detects_moov_before_mdat():
    def atom(kind: bytes, size: int) -> bytes:
        return size.to_bytes(4, "big") + kind + b"\x00" * (size - 8)

    assert media.faststart_prefix(atom(b"ftyp", 16) + atom(b"moov", 24) + atom(b"mdat", 16)) is True
    assert media.faststart_prefix(atom(b"ftyp", 16) + atom(b"mdat", 32) + atom(b"moov", 24)) is False
    assert media.faststart_prefix(atom(b"ftyp", 16)) is False


def test_generate_thumb_uploads_jpeg_and_is_idempotent(db, storage, fake_ffmpeg):
    asset = _asset(db)
    storage.objects[asset.object_key] = b"\xff\xd8original"

    view = thumbs.generate_thumb(db, asset)
    assert view is not None and view.state == "ready"
    assert view.object_key.startswith(f"thumbs/{asset.id}/1/")
    assert storage.objects[view.object_key].startswith(b"\xff\xd8")
    row = db.query(AssetThumb).filter(AssetThumb.asset_id == asset.id).one()
    assert row.state == "ready" and row.width == 16 and row.height == 16

    # Второй вызов ничего не пересобирает.
    again = thumbs.generate_thumb(db, asset)
    assert again.object_key == view.object_key
    assert len([key for key in storage.objects if key.startswith("thumbs/")]) == 1


def test_generate_thumb_failure_is_recorded_not_fatal(db, storage, broken_ffmpeg):
    asset = _asset(db, filename="photo.png")
    storage.objects[asset.object_key] = b"\x89PNG\r\n"
    view = thumbs.generate_thumb(db, asset)
    assert view is not None and view.state == "failed"
    assert view.object_key is None
    assert db.query(AssetThumb).filter(AssetThumb.asset_id == asset.id).one().error


def test_new_version_gets_its_own_thumb(db, storage, fake_ffmpeg):
    asset = _asset(db)
    storage.objects[asset.object_key] = b"\xff\xd8v1"
    first = thumbs.generate_thumb(db, asset)

    asset.version = 2
    asset.object_key = f"modules/{uuid.uuid4().hex}/photo.jpg"
    db.commit()
    storage.objects[asset.object_key] = b"\xff\xd8v2"
    second = thumbs.generate_thumb(db, asset)

    assert first.object_key != second.object_key
    assert second.object_key.startswith(f"thumbs/{asset.id}/2/")


def test_thumbnail_endpoint_serves_cached_jpeg(db, storage, fake_ffmpeg, client, make_user, make_module):
    from app.models.submodule_asset import SubmoduleAssetMap
    from app.models.user import UserRole

    module, lesson, _ = make_module()
    asset = _asset(db)
    db.add(SubmoduleAssetMap(submodule_id=lesson.id, asset_id=asset.id, order=1))
    db.commit()
    storage.objects[asset.object_key] = b"\xff\xd8original"
    token = make_user(UserRole.admin)[1]

    first = client.get(f"/assets/{asset.id}/thumb", headers=token)
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    assert first.headers["cache-control"].startswith("private")
    etag = first.headers["etag"]
    assert first.content.startswith(b"\xff\xd8")

    cached = client.get(f"/assets/{asset.id}/thumb", headers={**token, "If-None-Match": etag})
    assert cached.status_code == 304

    # Картинка не пишет событие обучения: список файлов — не просмотр материала.
    from sqlalchemy import func, select
    from app.models.audit import LearningEvent
    assert db.scalar(select(func.count(LearningEvent.id))) == 0


def test_thumbnail_endpoint_returns_404_with_retry_after_when_unavailable(db, storage, broken_ffmpeg, client, make_user, make_module):
    from app.models.submodule_asset import SubmoduleAssetMap
    from app.models.user import UserRole

    _, lesson, _ = make_module()
    asset = _asset(db)
    db.add(SubmoduleAssetMap(submodule_id=lesson.id, asset_id=asset.id, order=1))
    db.commit()
    storage.objects[asset.object_key] = b"\xff\xd8original"
    headers = make_user(UserRole.admin)[1]

    response = client.get(f"/assets/{asset.id}/thumb", headers=headers)
    assert response.status_code == 404
    assert response.headers.get("retry-after") == "6"


def test_quick_video_ready_accepts_faststart_mp4_without_download(db, storage, monkeypatch):
    def atom(kind: bytes, size: int) -> bytes:
        return size.to_bytes(4, "big") + kind + b"\x00" * (size - 8)

    asset = _asset(db, filename="video.mp4")
    storage.objects[asset.object_key] = atom(b"ftyp", 16) + atom(b"moov", 24) + atom(b"mdat", 4096)
    monkeypatch.setattr(media, "probe_url", lambda url: {"streams": [
        {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "width": 1280, "height": 720,
         "level": 40, "avg_frame_rate": "25/1"},
        {"codec_type": "audio", "codec_name": "aac"}]})

    ready, reason = media.quick_video_ready(storage, asset.bucket, asset.object_key, asset.original_filename, 5000)
    assert ready is True, reason


def test_quick_video_ready_rejects_moov_at_end_and_other_containers(db, storage, monkeypatch):
    def atom(kind: bytes, size: int) -> bytes:
        return size.to_bytes(4, "big") + kind + b"\x00" * (size - 8)

    asset = _asset(db, filename="video.mp4")
    storage.objects[asset.object_key] = atom(b"ftyp", 16) + atom(b"mdat", 4096) + atom(b"moov", 24)
    ready, reason = media.quick_video_ready(storage, asset.bucket, asset.object_key, asset.original_filename, 5000)
    assert ready is False and "faststart" in str(reason)

    mov = _asset(db, filename="video.mov")
    storage.objects[mov.object_key] = b"\x00\x00\x00\x10ftyp"
    ready, reason = media.quick_video_ready(storage, mov.bucket, mov.object_key, mov.original_filename, 12)
    assert ready is False and "переупаковки" in str(reason)


def test_thumb_objects_are_deleted_with_asset(db, storage, fake_ffmpeg, client, make_user, make_module):
    from app.models.submodule_asset import SubmoduleAssetMap
    from app.models.user import UserRole

    module, lesson, _ = make_module()
    asset = _asset(db)
    db.add(SubmoduleAssetMap(submodule_id=lesson.id, asset_id=asset.id, order=1))
    db.commit()
    storage.objects[asset.object_key] = b"\xff\xd8original"
    view = thumbs.generate_thumb(db, asset)
    thumb_key = view.object_key
    assert thumb_key in storage.objects

    asset.is_archived = True
    db.commit()
    headers = make_user(UserRole.admin)[1]
    revision = client.get(f"/admin/content/modules/{module.id}", headers=headers).json()["module"]["content_revision"]
    deleted = client.post(f"/admin/content/modules/{module.id}/assets/delete", headers=headers,
                          json={"revision": revision, "ids": [str(asset.id)]})
    assert deleted.status_code == 200, deleted.text
    assert thumb_key not in storage.objects
    assert db.query(AssetThumb).filter(AssetThumb.asset_id == asset.id).count() == 0
