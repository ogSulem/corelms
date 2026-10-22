import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.asset import AssetRevision, ContentAsset
from app.models.media import AssetRendition
from app.models.module import Module, Submodule
from app.models.submodule_asset import SubmoduleAssetMap
from app.services import media
from app.services.content import referenced_storage_keys


@pytest.fixture()
def video(db, make_module, storage, monkeypatch):
    module, lesson, _ = make_module()
    asset = ContentAsset(module_id=module.id, bucket='recorded-bucket', object_key='original/clip.avi',
        original_filename='clip.avi', checksum_sha256=hashlib.sha256(b'original video').hexdigest(), size_bytes=14)
    db.add(asset); db.flush()
    db.add(SubmoduleAssetMap(submodule_id=lesson.id, asset_id=asset.id, order=1)); db.flush()
    row = media.stage_rendition(db, asset); db.commit()
    storage.objects[asset.object_key] = b'original video'
    def encode(source, target):
        assert source.read_bytes() == b'original video'
        target.write_bytes(b'browser video'); return True
    monkeypatch.setattr(media, 'prepare_video', encode)
    return module, lesson, asset, row


def test_browser_rendition_never_replaces_original_or_advances_learning_revision(client, db, video, storage, make_user):
    module, _, asset, row = video
    old_revision = module.content_revision
    result = media.process_media_job(str(row.id))
    assert result['ok'], result
    db.expire_all(); current = db.get(ContentAsset, asset.id); row = db.get(AssetRendition, row.id)
    assert current.version == 1 and current.object_key == 'original/clip.avi' and current.original_filename == 'clip.avi'
    assert row.state == 'ready' and row.object_key.startswith('renditions/') and row.source_version == 1
    assert storage.objects[current.object_key] == b'original video'
    assert db.get(Module, module.id).content_revision == old_revision
    assert db.scalar(select(func.count()).select_from(AssetRevision)) == 0
    assert {current.object_key, row.object_key}.issubset(referenced_storage_keys(db))
    _, headers = make_user()
    status = client.get(f'/assets/{asset.id}/viewer', headers=headers).json()
    assert status['state'] == 'ready' and not status['can_retry']
    stream = client.get(f'/assets/{asset.id}/stream?variant=browser', headers={**headers, 'Range': 'bytes=0-6'})
    assert stream.status_code == 206 and stream.content == b'browser' and stream.headers['content-type'] == 'video/mp4'
    assert stream.headers['content-disposition'].endswith("clip.mp4")
    assert client.get(f'/assets/{asset.id}/download?variant=browser', headers=headers).content == b'original video'


@pytest.mark.parametrize('change', ['replace', 'asset_archive', 'lesson_archive', 'module_archive'])
def test_worker_cannot_publish_superseded_or_archived_source(db, video, storage, monkeypatch, change):
    module, lesson, asset, row = video
    def encode(source, target):
        with SessionLocal() as other:
            item = other.get(ContentAsset, asset.id)
            if change == 'replace':
                item.object_key, item.version = 'manual/new.avi', 2
                other.flush(); media.stage_rendition(other, item)
            elif change == 'asset_archive': item.is_archived = True
            elif change == 'lesson_archive': other.get(Submodule, lesson.id).is_archived = True
            else: other.get(Module, module.id).is_archived = True
            other.commit()
        target.write_bytes(b'obsolete derived data'); return True
    monkeypatch.setattr(media, 'prepare_video', encode)
    assert media.process_media_job(str(row.id))['skipped']
    db.expire_all()
    assert db.get(AssetRendition, row.id).state == 'skipped'
    assert storage.deleted == storage.uploaded and 'original/clip.avi' in storage.objects
    assert all(key.startswith('renditions/') for key in storage.deleted)


def test_failed_media_is_downloadable_retryable_and_restored_source_reuses_copy(client, db, video, storage, monkeypatch, admin_headers, make_user):
    _, _, asset, row = video
    def fail(*args): raise FileNotFoundError('ffmpeg')
    monkeypatch.setattr(media, 'prepare_video', fail)
    assert not media.process_media_job(str(row.id))['ok']
    db.expire_all(); assert db.get(AssetRendition, row.id).state == 'failed'
    _, headers = make_user()
    assert client.get(f'/assets/{asset.id}/stream?variant=browser', headers=headers).status_code == 409
    assert client.get(f'/assets/{asset.id}/download', headers=headers).content == b'original video'
    assert client.post(f'/assets/{asset.id}/viewer/retry', headers=headers).status_code == 403
    assert client.post(f'/assets/{asset.id}/viewer/retry', headers=admin_headers).status_code == 202
    def encode(source, target): target.write_bytes(b'good'); return True
    monkeypatch.setattr(media, 'prepare_video', encode)
    assert media.process_media_job(str(row.id))['ok']
    db.expire_all(); asset = db.get(ContentAsset, asset.id); asset.version += 1; db.flush()
    reused = media.stage_rendition(db, asset); db.commit()
    assert reused.state == 'ready' and reused.object_key == db.get(AssetRendition, row.id).object_key
    assert len(storage.uploaded) == 1


def test_ambiguous_publication_retains_output_for_reconciliation(db, video, storage, monkeypatch):
    _, _, asset, row = video
    commits = []
    class Uncertain(Session):
        def commit(self):
            super().commit(); commits.append(1)
            if len(commits) == 2:
                raise RuntimeError('Commit response lost after successful SQL commit')
    monkeypatch.setattr(media, 'SessionLocal', lambda: Uncertain(bind=db.get_bind()))
    result = media.process_media_job(str(row.id))
    assert not result['ok'] and result['publication_uncertain']
    db.expire_all(); ready = db.get(AssetRendition, row.id)
    assert ready.state == 'ready' and ready.object_key in storage.objects and not storage.deleted
    assert db.get(ContentAsset, asset.id).object_key == 'original/clip.avi'


def test_durable_outbox_recovers_interrupted_enqueue_and_expired_claim(db, video, monkeypatch):
    _, _, _, row = video
    monkeypatch.setattr(media.settings, 'media_dispatcher_enabled', True)
    monkeypatch.setattr(media, 'fetch_job', lambda _id: None)
    queue = []
    def enqueue(*args, **kwargs): queue.append(kwargs['job_id'])
    monkeypatch.setattr(media, 'get_queue', lambda _name: SimpleNamespace(enqueue=enqueue))
    assert media.dispatch_pending_media() == 1
    db.expire_all(); row = db.get(AssetRendition, row.id)
    assert row.state == 'queued' and row.job_id == queue[0]
    assert media.dispatch_pending_media() == 0
    row.updated_at = media.utcnow() - timedelta(minutes=3); db.commit()
    assert media.dispatch_pending_media() == 1
    db.refresh(row); assert row.job_id != queue[0]
    row.state = 'processing'; row.run_token = 'dead-owner'; row.attempt_count = 1
    row.updated_at = media.utcnow() - timedelta(seconds=media.settings.media_timeout_seconds + 301); db.commit()
    monkeypatch.setattr(media, 'fetch_job', lambda _id: SimpleNamespace(get_status=lambda **kw: 'started'))
    assert media.dispatch_pending_media() == 1  # Stale RQ status cannot strand a hard-expired claim.
    db.refresh(row); assert row.state == 'queued' and row.run_token is None
    row.state = 'processing'; row.attempt_count = 3
    row.updated_at = media.utcnow() - timedelta(seconds=media.settings.media_timeout_seconds + 301); db.commit()
    assert media.dispatch_pending_media() == 0
    db.refresh(row); assert row.state == 'failed'


def test_old_version_and_unrelated_claim_are_never_served(client, db, video, admin_headers):
    _, _, asset, row = video
    row.state, row.object_key, row.bucket, row.mime_type = 'ready', 'wrong.mp4', 'testing', 'video/mp4'
    asset.version = 2; asset.object_key = 'new/source.avi'; db.commit()
    assert client.get(f'/assets/{asset.id}/stream?variant=browser', headers=admin_headers).status_code == 409
    response = client.get(f'/assets/{asset.id}/viewer', headers=admin_headers)
    assert response.status_code == 200 and response.json()['state'] == 'pending' and response.json()['source_version'] == 2


def test_media_claim_stops_superseded_process_on_checkpoint(db, video, monkeypatch):
    _, _, asset, row = video
    row.state, row.run_token = 'processing', 'ours'; db.commit()
    token = media._active_claim.set({'id': row.id, 'token': 'ours', 'next_check': 0})
    try:
        asset.is_archived = True; db.commit()
        with pytest.raises(media.MediaSuperseded): media.checkpoint()
    finally:
        media._active_claim.reset(token)


FFMPEG = os.getenv('TEST_FFMPEG_BINARY') or shutil.which('ffmpeg')
FFPROBE = os.getenv('TEST_FFPROBE_BINARY') or shutil.which('ffprobe')


@pytest.mark.skipif(not FFMPEG or not FFPROBE, reason='requires ffmpeg and ffprobe for a real encoding test')
def test_real_avi_becomes_verified_faststart_mp4_and_is_not_reencoded_again(tmp_path, monkeypatch):
    monkeypatch.setattr(media.settings, 'ffmpeg_binary', FFMPEG)
    monkeypatch.setattr(media.settings, 'ffprobe_binary', FFPROBE)
    source = tmp_path / 'source.avi'; target = tmp_path / 'browser.mp4'
    subprocess.run([FFMPEG, '-nostdin', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=navy:s=320x180:r=24',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '1.5', '-c:v', 'mpeg4', '-c:a', 'pcm_s16le', str(source)], check=True, timeout=30)
    before = source.read_bytes()
    assert media.prepare_video(source, target)
    assert media.browser_compatible(media.probe(target)) and media.mp4_faststart(target)
    assert source.read_bytes() == before
    assert media.prepare_video(target, tmp_path / 'unnecessary.mp4') is False
    assert not (tmp_path / 'unnecessary.mp4').exists()


def test_office_command_has_private_profile_no_application_secrets_and_keeps_source(tmp_path, monkeypatch):
    fixture = Path(__file__).resolve().parents[2] / 'frontend/e2e/fixtures/guide.docx'
    source = tmp_path / 'source.docx'; source.write_bytes(fixture.read_bytes())
    before = source.read_bytes(); target = tmp_path / 'browser.pdf'
    observed = []
    monkeypatch.setenv('JWT_SECRET_KEY', 'do-not-pass-this-to-converters')
    def render(args, **kwargs):
        observed.append((args, kwargs))
        source.with_suffix('.pdf').write_bytes(b'%PDF-1.4\nsynthetic renderer output')
    monkeypatch.setattr(media, 'run_command', render)
    text = media.prepare_office(source, target)
    assert 'Инструкция' in text and source.read_bytes() == before and target.read_bytes().startswith(b'%PDF-')
    args, options = observed[0]
    assert '--headless' in args and '--convert-to' in args and options['timeout'] <= 180
    assert 'JWT_SECRET_KEY' not in options['env'] and 'S3_SECRET_ACCESS_KEY' not in options['env']
    config = (tmp_path / 'office-profile/user/registrymodifications.xcu').read_text()
    assert 'MacroSecurityLevel' in config and '<value>3</value>' in config


def test_converter_environment_is_sanitized(tmp_path, monkeypatch):
    import sys
    import json
    monkeypatch.setenv('TEST_PRIVATE_CREDENTIAL', 'must-not-reach-child')
    media.run_command([sys.executable, '-c', "import os,json;open('env.json','w').write(json.dumps(dict(os.environ)))"], cwd=tmp_path, timeout=10)
    assert 'TEST_PRIVATE_CREDENTIAL' not in json.loads((tmp_path / 'env.json').read_text())


def test_cancellation_kills_the_entire_converter_process_group(tmp_path, monkeypatch):
    import signal
    seen = []
    class Process:
        pid = 123456
        returncode = None
        def poll(self): return self.returncode
        def wait(self, timeout=None):
            if seen: self.returncode = 0; return 0
            raise subprocess.TimeoutExpired('converter', 1)
    def launch(*args, **kwargs):
        assert kwargs['start_new_session'] is True
        return Process()
    def stop(pid, sig): seen.append((pid, sig))
    calls = []
    def checkpoint():
        calls.append(1)
        if len(calls) > 1: raise media.MediaCanceled('Canceled')
    monkeypatch.setattr(media.subprocess, 'Popen', launch)
    monkeypatch.setattr(media.os, 'killpg', stop)
    monkeypatch.setattr(media, 'checkpoint', checkpoint)
    with pytest.raises(media.MediaCanceled): media.run_command(['converter'], cwd=tmp_path, timeout=10)
    assert seen == [(123456, signal.SIGTERM), (123456, signal.SIGKILL)]


LIBREOFFICE = os.getenv('TEST_LIBREOFFICE_BINARY') or shutil.which('libreoffice')


@pytest.mark.skipif(not LIBREOFFICE, reason='native LibreOffice required; installed in CI and the media Docker target')
def test_real_office_renderer_produces_readable_pdf_without_altering_docx(tmp_path, monkeypatch):
    from pypdf import PdfReader
    monkeypatch.setattr(media.settings, 'libreoffice_binary', LIBREOFFICE)
    fixture = Path(__file__).resolve().parents[2] / 'frontend/e2e/fixtures/guide.docx'
    source = tmp_path / 'source.docx'; source.write_bytes(fixture.read_bytes())
    target = tmp_path / 'browser.pdf'
    text = media.prepare_office(source, target)
    assert source.read_bytes() == fixture.read_bytes() and 'Инструкция' in text
    pdf = PdfReader(target)
    assert len(pdf.pages) >= 1 and 'консультацией' in '\n'.join(page.extract_text() for page in pdf.pages)


@pytest.mark.parametrize('status', ['queued', 'started'])
def test_dispatch_recovers_orphan_rq_hash_or_started_job_that_never_claimed_sql(db, video, monkeypatch, status):
    _, _, _, row = video
    row.state, row.job_id = 'queued', 'lost-job'
    row.updated_at = media.utcnow() - timedelta(minutes=3); db.commit()
    monkeypatch.setattr(media.settings, 'media_dispatcher_enabled', True)
    monkeypatch.setattr(media, 'fetch_job', lambda _id: SimpleNamespace(get_status=lambda **kw: status))
    sent = []
    monkeypatch.setattr(media, 'get_queue', lambda _name: SimpleNamespace(get_job_position=lambda _id: None,
        enqueue=lambda *args, **kwargs: sent.append(kwargs['job_id'])))
    assert media.dispatch_pending_media() == 1
    db.refresh(row); assert row.job_id == sent[0] and row.job_id != 'lost-job'
