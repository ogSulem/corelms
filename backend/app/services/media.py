"""Durable media outbox and original-preserving browser renditions.

The API stores an outbox row in the upload transaction. Dispatch and conversion
are separate: S3/Redis outages cannot roll back a published original. A worker
may publish only for the captured source version and its own claim token.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import subprocess
import signal
from contextvars import ContextVar
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from rq import get_current_job
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.queue import fetch_job, get_job_status, get_queue
from app.db.session import SessionLocal
from app.models.asset import ContentAsset
from app.models.media import AssetRendition
from app.models.module import Module, Submodule
from app.models.sales import SalesEntry
from app.models.submodule_asset import SubmoduleAssetMap
from app.services.document_preview import MAX_BYTES, build_preview
from app.services.storage import effective_bucket, get_s3_client

log = logging.getLogger(__name__)
VIDEO_EXTENSIONS = {"mp4", "mov", "m4v", "mkv", "avi", "webm", "wmv", "flv", "mpeg", "mpg", "mts", "m2ts", "3gp", "ogv"}
OFFICE_EXTENSIONS = {"docx", "pptx"}
MAX_OUTPUT_BYTES = 1024 * 1024 * 1024
_active_claim: ContextVar[dict | None] = ContextVar("media_claim", default=None)


def utcnow():
    return datetime.now(timezone.utc)


def media_kind(filename: str) -> str | None:
    ext = pathlib.PurePosixPath(filename).suffix.lower().lstrip(".")
    return "video" if ext in VIDEO_EXTENSIONS else "office" if ext in OFFICE_EXTENSIONS else None


def current_rendition(db: Session, asset: ContentAsset) -> AssetRendition | None:
    return db.scalar(select(AssetRendition).where(AssetRendition.asset_id == asset.id,
        AssetRendition.source_version == asset.version, AssetRendition.source_bucket == asset.bucket,
        AssetRendition.source_object_key == asset.object_key))


def stage_rendition(db: Session, asset: ContentAsset, *, retry: bool = False) -> AssetRendition | None:
    if not media_kind(asset.original_filename):
        return None
    db.execute(update(AssetRendition).where(AssetRendition.asset_id == asset.id,
        AssetRendition.source_version != asset.version, AssetRendition.state.in_(["pending", "queued", "processing"]))
        .values(state="skipped", run_token=None, updated_at=utcnow()))
    row = current_rendition(db, asset)
    if row is None:
        row = AssetRendition(asset_id=asset.id, source_version=asset.version,
            source_bucket=asset.bucket, source_object_key=asset.object_key)
        # Restoring an immutable original can reuse an already verified browser copy.
        previous = db.scalar(select(AssetRendition).where(AssetRendition.asset_id == asset.id,
            AssetRendition.source_bucket == asset.bucket, AssetRendition.source_object_key == asset.object_key,
            AssetRendition.state == "ready").limit(1))
        if previous:
            for field in ("state", "bucket", "object_key", "mime_type", "size_bytes", "checksum_sha256", "text_content"):
                setattr(row, field, getattr(previous, field))
        db.add(row)
    elif (retry and row.state in {"failed", "skipped"}) or (row.state == "skipped" and asset_is_active(db, asset)):
        row.state, row.job_id, row.run_token, row.error, row.updated_at = "pending", None, None, None, utcnow()
        row.attempt_count = 0
    return row


def asset_is_active(db: Session, asset: ContentAsset) -> bool:
    if asset.is_archived:
        return False
    entry = db.scalar(select(SalesEntry).where(SalesEntry.asset_id == asset.id))
    if entry:
        from app.services.sales_library import path_is_visible
        return not entry.is_archived and path_is_visible(db, entry.section, entry.path)
    parents = list(db.execute(select(Submodule.module_id, Submodule.is_archived).join(SubmoduleAssetMap,
        SubmoduleAssetMap.submodule_id == Submodule.id).where(SubmoduleAssetMap.asset_id == asset.id)))
    mids = {mid for mid, archived in parents if not archived}
    if asset.module_id and not parents:
        mids.add(asset.module_id)
    return bool(mids and db.scalar(select(Module.id).where(Module.id.in_(mids), Module.is_archived.is_(False)).limit(1)))


def dispatch_pending_media(*, limit: int = 12) -> int:
    """Safe to call from several API instances; short leases + worker CAS dedupe.

    Queued rows whose enqueue was interrupted are retried. Processing claims are
    never stolen until the hard worker timeout has elapsed.
    """
    if not settings.media_dispatcher_enabled:
        return 0
    now = utcnow()
    count = 0
    with SessionLocal() as db:
        ids = list(db.scalars(select(AssetRendition.id).where(or_(
            AssetRendition.state == "pending",
            and_(AssetRendition.state == "queued", AssetRendition.updated_at < now - timedelta(seconds=120)),
            and_(AssetRendition.state == "processing", AssetRendition.updated_at < now - timedelta(seconds=settings.media_timeout_seconds + 300)),
        )).order_by(AssetRendition.updated_at).limit(limit)))
    for rid in ids:
        try:
            with SessionLocal() as db:
                row = db.scalar(select(AssetRendition).where(AssetRendition.id == rid).with_for_update(skip_locked=True))
                if not row or row.state not in {"pending", "queued", "processing"}:
                    continue
                stamp = row.updated_at.replace(tzinfo=timezone.utc) if row.updated_at.tzinfo is None else row.updated_at
                if row.state == "queued" and stamp > now - timedelta(seconds=120):
                    continue
                if row.state == "processing" and stamp > now - timedelta(seconds=settings.media_timeout_seconds + 300):
                    continue
                asset = db.get(ContentAsset, row.asset_id)
                if not asset or (asset.version, asset.bucket, asset.object_key) != (row.source_version, row.source_bucket, row.source_object_key) or not asset_is_active(db, asset):
                    row.state, row.updated_at = "skipped", now
                    db.commit()
                    continue
                if row.attempt_count >= 3:
                    row.state, row.error, row.updated_at = "failed", "Обработчик неоднократно прерывался. Проверьте ресурсы и формат; затем повторите подготовку вручную.", now
                    db.commit()
                    continue
                previous = fetch_job(row.job_id) if row.job_id else None
                previous_status = get_job_status(previous) if previous else None
                # A started RQ job that never acquired the SQL claim is stranded
                # after this 120s lease; a new job ID prevents the old one claiming.
                waiting = previous_status in {"scheduled", "deferred"} or (
                    previous_status == "queued" and get_queue(settings.rq_queue_media).get_job_position(row.job_id) is not None)
                if row.state == "queued" and waiting:
                    row.updated_at = now
                    db.commit()
                    continue
                aid = str(asset.id)
                job_id = uuid.uuid4().hex
                row.state, row.job_id, row.run_token, row.updated_at = "queued", job_id, None, now
                db.commit()
            # A crash here leaves a recoverable queued outbox entry, not a lost file.
            get_queue(settings.rq_queue_media).enqueue(process_media_job, str(rid), job_id=job_id,
                job_timeout=settings.media_timeout_seconds + 60, result_ttl=86400, failure_ttl=7 * 86400,
                meta={"job_kind": "media", "asset_id": aid, "rendition_id": str(rid)})
            count += 1
        except Exception:
            log.warning("Media outbox dispatch deferred for %s", rid, exc_info=True)
    return count


class MediaCanceled(Exception):
    pass


class MediaSuperseded(MediaCanceled):
    pass


def checkpoint():
    claim = _active_claim.get()
    if claim and time.monotonic() > claim["next_check"]:
        claim["next_check"] = time.monotonic() + 15
        with SessionLocal() as db:
            row = db.get(AssetRendition, claim["id"])
            asset = db.get(ContentAsset, row.asset_id) if row else None
            if not row or row.run_token != claim["token"] or not asset or (asset.version, asset.bucket, asset.object_key) != (row.source_version, row.source_bucket, row.source_object_key) or not asset_is_active(db, asset):
                raise MediaSuperseded("Материал изменён или перемещён в архив. Подготовка старой версии остановлена.")
    job = get_current_job()
    if job:
        job.refresh()
        if (job.meta or {}).get("cancel_requested"):
            raise MediaCanceled("Подготовка отменена. Оригинал сохранён.")


def run_command(args: list[str], *, cwd: pathlib.Path, timeout: int, env: dict | None = None):
    checkpoint()
    proc = None
    try:
        with tempfile.TemporaryFile() as errors:
            process_env = env or {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "HOME": str(cwd), "TMPDIR": str(cwd)}
            proc = subprocess.Popen(args, cwd=cwd, env=process_env, stdin=subprocess.DEVNULL,
                                    stdout=errors, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                checkpoint()
                if time.monotonic() >= deadline:
                    raise RuntimeError("Подготовка превысила допустимое время. Оригинал доступен для скачивания.")
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            if proc.returncode:
                errors.seek(0, 2)
                errors.seek(max(0, errors.tell() - 2000))
                log.warning("Media tool failed: %s", errors.read().decode("utf-8", errors="replace"))
                raise RuntimeError("Не удалось подготовить копию для браузера. Оригинал сохранён; проверьте формат файла.")
    finally:
        if proc is not None:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            # Reap grandchildren even if their launcher has already exited.
            # Every command owns a new process group; no unrelated processes.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if proc.poll() is None:
                proc.wait()


def probe(path: pathlib.Path) -> dict:
    result = subprocess.run([settings.ffprobe_binary, "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_entries", "stream=codec_type,codec_name,pix_fmt,width,height,level,avg_frame_rate:format=duration,format_name",
        "-of", "json", str(path)], capture_output=True, timeout=25, check=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"})
    if len(result.stdout) > 128 * 1024:
        raise RuntimeError("Слишком сложная структура видео")
    return json.loads(result.stdout)


def browser_compatible(info: dict) -> bool:
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    fraction = str(video.get("avg_frame_rate") or "0/1").split("/")
    fps = float(fraction[0]) / max(1, float(fraction[1])) if len(fraction) == 2 else float(fraction[0])
    return (fps <= 60 and int(video.get("level") or 0) <= 42 and video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p"
            and int(video.get("width") or 0) <= 1920 and int(video.get("height") or 0) <= 1080
            and all(s.get("codec_name") == "aac" for s in audio))


def mp4_faststart(path: pathlib.Path) -> bool:
    """Read atom headers only, never load a multi-GB mdat into memory."""
    length = path.stat().st_size
    with path.open("rb") as stream:
        for _ in range(1000):
            header = stream.read(8)
            if len(header) != 8:
                return False
            size, kind = int.from_bytes(header[:4], "big"), header[4:]
            base = 8
            if size == 1:
                extra = stream.read(8)
                if len(extra) != 8:
                    return False
                size, base = int.from_bytes(extra, "big"), 16
            if kind == b"moov":
                return True
            if kind == b"mdat" or size < base or stream.tell() + size - base > length:
                return False
            stream.seek(size - base, 1)
    return False


def prepare_video(source: pathlib.Path, target: pathlib.Path) -> bool:
    """Returns False when the original is already a safe fast-start MP4."""
    info = probe(source)
    compatible = browser_compatible(info)
    container = str(info.get("format", {}).get("format_name") or "")
    if compatible and source.suffix == ".mp4" and "mp4" in container and mp4_faststart(source):
        return False
    command = [settings.ffmpeg_binary, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-protocol_whitelist", "file,pipe", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
    if compatible:
        command += ["-c", "copy"]  # Fast remux instead of needless lossy re-encoding.
    else:
        command += ["-c:v", "libx264", "-threads", str(settings.media_encoder_threads), "-preset", "veryfast", "-crf", "23",
            "-vf", "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p",
            "-r", "30", "-profile:v", "high", "-level:v", "4.1", "-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    command += ["-map_metadata", "-1", "-movflags", "+faststart", "-fs", str(MAX_OUTPUT_BYTES), str(target)]
    run_command(command, cwd=source.parent, timeout=settings.media_timeout_seconds)
    output = probe(target)
    if not browser_compatible(output):
        raise RuntimeError("Подготовленная копия не прошла проверку совместимости")
    original_duration = float(info.get("format", {}).get("duration") or 0)
    output_duration = float(output.get("format", {}).get("duration") or 0)
    if original_duration and abs(original_duration - output_duration) > max(.25, min(2, original_duration * .002)):
        raise RuntimeError("Подготовленная копия неполная. Используйте оригинал или уменьшите размер видео.")
    return True


def prepare_office(source: pathlib.Path, target: pathlib.Path) -> str:
    if source.stat().st_size > MAX_BYTES:
        raise RuntimeError("Офисный документ больше 25 МБ. Для полного просмотра используйте оригинал.")
    # Also yields a bounded text source for an explicitly requested quiz draft.
    preview = build_preview(source.read_bytes(), source.name)
    text = "\n\n".join(b["text"] for b in preview.get("blocks", []))[:300_000]
    profile = source.parent / "office-profile"
    (profile / "user").mkdir(parents=True)
    (profile / "user" / "registrymodifications.xcu").write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item><item oor:path="/org.openoffice.Inet/Settings"><prop oor:name="ooInetProxyType" oor:op="fuse"><value>2</value></prop><prop oor:name="ooInetHTTPProxyName" oor:op="fuse"><value>127.0.0.1</value></prop><prop oor:name="ooInetHTTPProxyPort" oor:op="fuse"><value>9</value></prop><prop oor:name="ooInetHTTPSProxyName" oor:op="fuse"><value>127.0.0.1</value></prop><prop oor:name="ooInetHTTPSProxyPort" oor:op="fuse"><value>9</value></prop><prop oor:name="ooInetNoProxy" oor:op="fuse"><value></value></prop></item></oor:items>''', encoding="utf-8")
    # Never pass database, signing or object-store credentials to office processes.
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(profile), "TMPDIR": str(source.parent),
           "LANG": "C.UTF-8", "SAL_USE_VCLPLUGIN": "svp", "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9", "no_proxy": ""}
    run_command([settings.libreoffice_binary, "--headless", "--nologo", "--nodefault", "--norestore", "--nolockcheck",
        f"-env:UserInstallation={profile.as_uri()}", "--convert-to", "pdf", "--outdir", str(source.parent), str(source)],
        cwd=source.parent, timeout=min(settings.media_timeout_seconds, 180), env=env)
    generated = source.with_suffix(".pdf")
    if not generated.exists() or generated.stat().st_size > MAX_OUTPUT_BYTES:
        raise RuntimeError("Не удалось подготовить PDF-копию. Откройте оригинал документа.")
    if generated != target:
        generated.rename(target)
    with target.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise RuntimeError("Подготовленная PDF-копия не прошла проверку")
    return text


def process_media_job(rendition_id: str) -> dict:
    rid, token = uuid.UUID(rendition_id), uuid.uuid4().hex
    job = get_current_job()
    with SessionLocal() as db:
        row = db.scalar(select(AssetRendition).where(AssetRendition.id == rid).with_for_update())
        if not row or row.state not in {"pending", "queued"} or (job and row.job_id != job.id):
            return {"ok": True, "skipped": True}
        asset = db.get(ContentAsset, row.asset_id)
        if not asset or not asset_is_active(db, asset) or (asset.version, asset.bucket, asset.object_key) != (row.source_version, row.source_bucket, row.source_object_key):
            row.state, row.updated_at = "skipped", utcnow()
            db.commit()
            return {"ok": True, "skipped": True}
        aid, version, source_bucket, source_key, filename = asset.id, asset.version, asset.bucket, asset.object_key, asset.original_filename
        checksum, kind = asset.checksum_sha256, media_kind(filename)
        row.state, row.run_token, row.error, row.updated_at = "processing", token, None, utcnow()
        row.attempt_count += 1
        db.commit()
    context_token = _active_claim.set({"id": rid, "token": token, "next_check": time.monotonic() + 15})
    s3 = None
    new_key = None
    committed = attempted = False
    output_bucket = effective_bucket()
    try:
        s3 = get_s3_client()
        checkpoint()
        with tempfile.TemporaryDirectory(prefix="corelms_media_") as tmp:
            root = pathlib.Path(tmp)
            source = root / ("source" + pathlib.PurePosixPath(filename).suffix.lower())
            obj = s3.get_object(Bucket=source_bucket, Key=source_key)
            body = obj["Body"]
            digest, size = hashlib.sha256(), 0
            try:
                with source.open("wb") as out:
                    while chunk := body.read(1024 * 1024):
                        checkpoint()
                        size += len(chunk)
                        if size > 1024 * 1024 * 1024:
                            raise RuntimeError("Файл больше лимита фоновой подготовки (1 ГБ). Оригинал сохранён.")
                        digest.update(chunk)
                        out.write(chunk)
            finally:
                body.close()
            if checksum and digest.hexdigest() != checksum:
                raise RuntimeError("Содержимое источника изменилось вне LMS. Проверьте оригинал перед повторной подготовкой.")
            target = root / ("browser.mp4" if kind == "video" else "browser.pdf")
            text = None
            changed = prepare_video(source, target) if kind == "video" else True
            if kind == "office":
                text = prepare_office(source, target)
            mime = "video/mp4" if kind == "video" else "application/pdf"
            if changed:
                if not target.exists() or not 0 < target.stat().st_size <= MAX_OUTPUT_BYTES:
                    raise RuntimeError("Подготовленная копия превышает допустимый размер")
                with target.open("rb") as stream:
                    output_hash = hashlib.file_digest(stream, "sha256").hexdigest()
                size = target.stat().st_size
                new_key = f"renditions/{aid}/{version}/{uuid.uuid4().hex}{target.suffix}"
                checkpoint()
                with target.open("rb") as stream:
                    s3.put_object(Bucket=output_bucket, Key=new_key, Body=stream, ContentType=mime)
                final_key, final_bucket = new_key, output_bucket
            else:
                final_key, final_bucket, output_hash = source_key, source_bucket, digest.hexdigest()
            checkpoint()
            with SessionLocal() as db:
                row = db.scalar(select(AssetRendition).where(AssetRendition.id == rid).with_for_update())
                asset = db.get(ContentAsset, aid)
                if not row or row.run_token != token or not asset or (asset.version, asset.bucket, asset.object_key) != (version, source_bucket, source_key) or not asset_is_active(db, asset):
                    if row and row.run_token == token:
                        row.state, row.updated_at = "skipped", utcnow()
                        db.commit()
                    return {"ok": True, "skipped": True}
                row.state, row.bucket, row.object_key, row.mime_type = "ready", final_bucket, final_key, mime
                row.size_bytes, row.checksum_sha256, row.text_content, row.updated_at = size, output_hash, text, utcnow()
                attempted = True
                db.commit()
                committed = True
        return {"ok": True, "asset_id": str(aid), "source_version": version}
    except Exception as exc:
        log.warning("Media preparation failed for %s", aid, exc_info=True)
        message = str(exc) if isinstance(exc, (RuntimeError, MediaCanceled)) else "Не удалось подготовить копию для браузера. Проверьте доступность обработчика; оригинал сохранён."
        if isinstance(exc, FileNotFoundError):
            message = "На обработчике не установлен ffmpeg/LibreOffice. Оригинал сохранён; администратор может повторить подготовку после настройки."
        if not attempted:
            with SessionLocal() as db:
                row = db.scalar(select(AssetRendition).where(AssetRendition.id == rid).with_for_update())
                if row and row.run_token == token:
                    row.state, row.error, row.updated_at = "skipped" if isinstance(exc, MediaSuperseded) else "failed", message[:1000], utcnow()
                    db.commit()
        return {"ok": False, "asset_id": str(aid), "error": message, "publication_uncertain": attempted}
    finally:
        _active_claim.reset(context_token)
        if new_key and not committed and not attempted:
            try:
                s3.delete_object(Bucket=output_bucket, Key=new_key)
            except Exception:
                log.warning("Unpublished rendition retained for reconciliation: %s", new_key)
