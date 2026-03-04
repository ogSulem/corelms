from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import pathlib
import random
import re
import shutil
import tempfile
import time
import unicodedata
import uuid
import zipfile
import unicodedata
from datetime import datetime

from botocore.exceptions import ClientError
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ResponseStreamingError
from rq import get_current_job

from app.core.config import settings
from app.core.queue import fetch_job, get_queue
from app.core.redis_client import get_redis
from app.db.session import SessionLocal
from app.models.module import Module
from app.models.quiz import Quiz
from app.services.module_importer import import_module_from_dir
from app.services.quiz_regeneration_jobs import regenerate_module_quizzes_job
from app.services.storage import ensure_bucket_exists, get_s3_client


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


def _persist_job_snapshot(*, job, meta: dict) -> None:
    try:
        job_id = str(getattr(job, "id", "") or "").strip()
        if not job_id:
            return

        result_payload = None
        try:
            st = str(job.get_status(refresh=True) or "").strip().lower()
            if st == "finished":
                res = job.result
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    result_payload = res
        except Exception:
            result_payload = None

        if isinstance(result_payload, dict):
            try:
                raw = json.dumps(result_payload, ensure_ascii=False)
                if len(raw) > 200_000:
                    result_payload = {"ok": bool(result_payload.get("ok", True)), "module_id": result_payload.get("module_id")}
            except Exception:
                result_payload = None

        payload = {
            "id": job_id,
            "status": str(job.get_status(refresh=True) or ""),
            "enqueued_at": job.enqueued_at.isoformat() if getattr(job, "enqueued_at", None) else None,
            "started_at": job.started_at.isoformat() if getattr(job, "started_at", None) else None,
            "ended_at": job.ended_at.isoformat() if getattr(job, "ended_at", None) else None,
            "queue": str(getattr(job, "origin", "") or "").strip() or None,
            "meta": meta,
            "result": result_payload,
            "ts": datetime.utcnow().isoformat(),
        }
        r = get_redis()
        r.set(f"admin:job_snapshot:{job_id}", json.dumps(payload, ensure_ascii=False))
        r.expire(f"admin:job_snapshot:{job_id}", 60 * 60 * 24 * 30)
    except Exception:
        return


def _bump_admin_jobs_rev() -> None:
    try:
        r = get_redis()
        r.incr("admin:jobs:rev")
        try:
            r.expire("admin:jobs:rev", 60 * 60 * 24 * 30)
        except Exception:
            pass
    except Exception:
        return


def _publish_admin_jobs_changed(*, job) -> None:
    try:
        r = get_redis()
        _bump_admin_jobs_rev()
        r.publish("admin:jobs:changed", str(getattr(job, "id", "") or "1"))
    except Exception:
        return


def _publish_admin_jobs_changed_throttled(*, job, meta: dict, force: bool = False) -> None:
    try:
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        last_ms = 0
        try:
            last_ms = int(meta.get("_admin_jobs_pub_at_ms") or 0)
        except Exception:
            last_ms = 0
        if (not force) and last_ms and (now_ms - last_ms) < 1000:
            return
        meta["_admin_jobs_pub_at_ms"] = now_ms
        _publish_admin_jobs_changed(job=job)
    except Exception:
        return


def _set_job_stage(*, stage: str, detail: str | None = None) -> None:
    try:
        job = get_current_job()
    except Exception:
        job = None
    if job is None:
        return

    try:
        now = datetime.utcnow()
        meta = dict(job.meta or {})

        # Stage timing
        # - stage_started_at: when current stage began
        # - stage_durations_s: {stage: seconds}
        # - job_started_at: when first stage was observed
        prev_stage = str(meta.get("stage") or "")
        prev_started_at = str(meta.get("stage_started_at") or "")
        if not meta.get("job_started_at"):
            meta["job_started_at"] = now.isoformat()

        if prev_stage and prev_started_at and prev_stage != str(stage):
            try:
                prev_dt = datetime.fromisoformat(prev_started_at)
                dur = max(0.0, (now - prev_dt).total_seconds())
                durs = dict(meta.get("stage_durations_s") or {})
                durs[prev_stage] = float(durs.get(prev_stage) or 0.0) + float(dur)
                meta["stage_durations_s"] = durs
            except Exception:
                pass

        meta["stage"] = str(stage)
        meta["stage_at"] = now.isoformat()
        meta["stage_started_at"] = now.isoformat()
        if detail is not None:
            meta["detail"] = str(detail)
        _publish_admin_jobs_changed_throttled(job=job, meta=meta, force=True)
        job.meta = meta
        job.save_meta()
        _persist_job_snapshot(job=job, meta=meta)
    except Exception:
        return


def _job_heartbeat(*, detail: str | None = None) -> None:
    try:
        job = get_current_job()
    except Exception:
        return

    try:
        now_dt = datetime.utcnow()
        now = now_dt.isoformat()
        meta = dict(job.meta or {})

        try:
            last = str(meta.get("_heartbeat_at") or "").strip()
            if last:
                last_dt = datetime.fromisoformat(last)
                if (now_dt - last_dt).total_seconds() < 3:
                    return
        except Exception:
            pass

        meta["stage_at"] = now
        if detail is not None:
            meta["detail"] = str(detail)
        meta["_heartbeat_at"] = now
        _publish_admin_jobs_changed_throttled(job=job, meta=meta, force=False)
        job.meta = meta
        job.save_meta()
        _persist_job_snapshot(job=job, meta=meta)
    except Exception:
        return


def _is_cancel_requested() -> bool:
    try:
        job = get_current_job()
    except Exception:
        job = None
    if job is None:
        return False
    try:
        meta = dict(job.meta or {})
        return bool(meta.get("cancel_requested"))
    except Exception:
        return False


class ImportCanceledError(RuntimeError):
    pass


def _cancel_checkpoint(*, s3_object_key: str, stage: str) -> None:
    if not _is_cancel_requested():
        return
    _set_job_stage(stage="canceled", detail=f"{stage}: cancel")
    raise ImportCanceledError("import canceled")


def _set_job_error(*, error: Exception, error_code: str | None = None, error_hint: str | None = None) -> None:
    try:
        job = get_current_job()
    except Exception:
        job = None
    if job is None:
        return

    try:
        meta = dict(job.meta or {})
        cls = type(error).__name__
        msg = str(error or "")

        code = str(error_code or "").strip() or "IMPORT_FAILED"
        hint = str(error_hint or "").strip()

        if not error_code:
            if isinstance(error, zipfile.BadZipFile) or "bad zip" in msg.lower() or "badzipfile" in msg.lower():
                code = "ZIP_INVALID"
                if not hint:
                    hint = "Проверьте, что ZIP не повреждён и содержит структуру модуля."
            elif "zip has too many files" in msg.lower():
                code = "ZIP_TOO_MANY_FILES"
                if not hint:
                    hint = "ZIP содержит слишком много файлов. Удалите лишнее или разбейте модуль на части."
            elif "zip uncompressed total too large" in msg.lower():
                code = "ZIP_TOO_LARGE"
                if not hint:
                    hint = "ZIP слишком большой после распаковки. Удалите тяжёлые материалы или разделите модуль."
            elif "zip entry too large" in msg.lower():
                code = "ZIP_ENTRY_TOO_LARGE"
                if not hint:
                    hint = "В ZIP есть слишком большой файл. Сожмите/уменьшите его или вынесите отдельно."
            elif "zip suspicious compression ratio" in msg.lower():
                code = "ZIP_SUSPICIOUS"
                if not hint:
                    hint = "ZIP похож на zip-bomb или содержит подозрительно сжатые данные. Проверьте архив."
            elif "module title already exists" in msg.lower() or "title already exists" in msg.lower():
                code = "DUPLICATE_MODULE_TITLE"
                if not hint:
                    hint = "Смените название модуля (или удалите существующий модуль с таким названием)."
            elif "failed to upload zip" in msg.lower() or "failed to enqueue" in msg.lower():
                code = "IMPORT_QUEUE_OR_UPLOAD_FAILED"
                if not hint:
                    hint = "Проверьте доступность Redis/worker и S3."

        meta["error_code"] = code
        meta["error_class"] = cls
        meta["error_message"] = msg
        if hint:
            meta["error_hint"] = hint
        _publish_admin_jobs_changed_throttled(job=job, meta=meta, force=True)
        job.meta = meta
        job.save_meta()
        _persist_job_snapshot(job=job, meta=meta)
    except Exception:
        return


def _safe_extract_zip(*, zf: zipfile.ZipFile, dest: pathlib.Path) -> None:
    dest = dest.resolve()
    max_files = int(getattr(settings, "import_zip_max_files", 12000) or 12000)
    max_total = int(getattr(settings, "import_zip_max_uncompressed_bytes", 2_500_000_000) or 2_500_000_000)
    max_entry = int(getattr(settings, "import_zip_max_entry_bytes", 750_000_000) or 750_000_000)
    max_ratio = int(getattr(settings, "import_zip_max_compression_ratio", 250) or 250)

    extracted_files = 0
    total_uncompressed = 0

    for member in zf.infolist():
        name = member.filename
        if name:
            try:
                raw = name.encode("cp437", errors="replace")
                candidates: list[str] = []
                for enc in ("utf-8", "cp866"):
                    try:
                        candidates.append(raw.decode(enc))
                    except Exception:
                        continue

                def score(s: str) -> int:
                    cyr = len(re.findall(r"[А-Яа-я]", s))
                    bad = s.count("�") + s.count("?")
                    return cyr * 10 - bad

                if candidates:
                    best = max(candidates, key=score)
                    if score(best) > score(name):
                        name = best
            except Exception:
                pass
        if not name or name.endswith("/"):
            continue

        extracted_files += 1
        if extracted_files > max_files:
            raise ValueError(f"zip has too many files: {extracted_files} > {max_files}")

        try:
            file_size = int(getattr(member, "file_size", 0) or 0)
        except Exception:
            file_size = 0
        try:
            comp_size = int(getattr(member, "compress_size", 0) or 0)
        except Exception:
            comp_size = 0

        if file_size > max_entry:
            raise ValueError(f"zip entry too large: {file_size} > {max_entry}: {name}")

        total_uncompressed += max(0, file_size)
        if total_uncompressed > max_total:
            raise ValueError(f"zip uncompressed total too large: {total_uncompressed} > {max_total}")

        # Detect classic zip-bomb patterns (tiny compressed -> huge uncompressed)
        # Note: allow small files and stored entries.
        if comp_size > 0 and file_size > 0:
            ratio = file_size / max(1, comp_size)
            if ratio > float(max_ratio) and file_size > 10_000_000:
                raise ValueError(f"zip suspicious compression ratio: {ratio:.1f} > {max_ratio}: {name}")

        target = (dest / name).resolve()
        if not str(target).startswith(str(dest)):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, length=1024 * 1024)


def import_module_zip_job(
    *,
    s3_object_key: str,
    title: str | None = None,
    source_filename: str | None = None,
    actor_user_id: str | None = None,
    module_id: str | None = None,
    enqueue_regen: bool = True,
) -> dict:
    log.info("import_module_zip_job: start s3_object_key=%s source_filename=%s title=%s", s3_object_key, source_filename, title)
    _set_job_stage(stage="start", detail=s3_object_key)
    ensure_bucket_exists()
    s3 = get_s3_client()

    cleanup_done = False

    def _cleanup_uploaded_keys_best_effort() -> None:
        # Best-effort cleanup of S3 objects uploaded during this job.
        # IMPORTANT: do NOT delete the source ZIP key.
        try:
            job = get_current_job()
        except Exception:
            job = None
        if job is None:
            return
        try:
            keys = list((job.meta or {}).get("uploaded_keys") or [])
        except Exception:
            keys = []
        if not keys:
            return

        try:
            ensure_bucket_exists()
            s3c = get_s3_client()
        except Exception:
            return

        src = str(s3_object_key or "").strip()
        for k in keys:
            try:
                kk = str(k or "").strip()
                if not kk:
                    continue
                if src and kk == src:
                    continue
                s3c.delete_object(Bucket=settings.s3_bucket, Key=kk)
            except Exception:
                continue

    def _release_enqueue_locks() -> None:
        try:
            r = get_redis()
        except Exception:
            return
        try:
            r.delete(f"admin:import_enqueued_by_object_key:{str(s3_object_key or '').strip()}")
        except Exception:
            pass
        try:
            norm_title = ""
            try:
                job = get_current_job()
                norm_title = str((job.meta or {}).get("import_title_norm") or "").strip()
            except Exception:
                norm_title = ""
            if norm_title:
                r.delete(f"admin:import_enqueued_by_title:{norm_title}")
        except Exception:
            pass

        try:
            fp = ""
            try:
                job = get_current_job()
                fp = str((job.meta or {}).get("import_fingerprint") or "").strip()
            except Exception:
                fp = ""
            if fp:
                r.delete(f"admin:import_enqueued_by_fingerprint:{fp}")
        except Exception:
            pass

    _cancel_checkpoint(s3_object_key=s3_object_key, stage="start")

    def _regen_dedupe_key(mid: str) -> str:
        return f"admin:regen_job_id_by_module_id:{str(mid).strip()}"

    def _get_existing_regen_job_id(*, module_id: str) -> str:
        try:
            r = get_redis()
        except Exception:
            return ""
        try:
            return str(r.get(_regen_dedupe_key(module_id)) or "").strip()
        except Exception:
            return ""

    def _set_existing_regen_job_id(*, module_id: str, regen_job_id: str) -> None:
        try:
            r = get_redis()
        except Exception:
            return
        try:
            r.set(_regen_dedupe_key(module_id), str(regen_job_id).strip())
            r.expire(_regen_dedupe_key(module_id), 60 * 60 * 6)
        except Exception:
            pass

    def _download_zip_with_retry(*, object_key: str, dest_path: pathlib.Path) -> None:
        tries = 4
        base = 0.6
        last: Exception | None = None
        for attempt in range(1, tries + 1):
            try:
                try:
                    if dest_path.exists():
                        dest_path.unlink(missing_ok=True)
                except Exception:
                    pass

                with dest_path.open("wb") as f:
                    _cancel_checkpoint(s3_object_key=object_key, stage="download")
                    _job_heartbeat(detail=f"download: {object_key}")
                    config = TransferConfig(
                        multipart_threshold=8 * 1024 * 1024,
                        multipart_chunksize=8 * 1024 * 1024,
                        max_concurrency=6,
                        use_threads=True,
                    )
                    try:
                        s3.download_fileobj(settings.s3_bucket, object_key, f, Config=config)
                    except Exception:
                        resp = s3.get_object(Bucket=settings.s3_bucket, Key=object_key)
                        body = resp.get("Body")
                        try:
                            while True:
                                _cancel_checkpoint(s3_object_key=object_key, stage="download")
                                _job_heartbeat(detail=f"download: {object_key}")
                                chunk = body.read(8 * 1024 * 1024) if body is not None else b""
                                if not chunk:
                                    break
                                f.write(chunk)
                        finally:
                            try:
                                if body is not None:
                                    body.close()
                            except Exception:
                                pass

                return
            except ImportCanceledError:
                raise
            except (ResponseStreamingError, OSError, IOError) as e:
                last = e
            except Exception as e:
                msg = str(e)
                if "IncompleteRead" in msg or "Connection broken" in msg:
                    last = e
                else:
                    raise

            if attempt >= tries:
                raise last if last is not None else Exception("download failed")
            try:
                time.sleep(base * (2 ** (attempt - 1)) + random.random() * 0.25)
            except Exception:
                pass

    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)
        zip_path = base / "module.zip"

        _set_job_stage(stage="download", detail=s3_object_key)
        _cancel_checkpoint(s3_object_key=s3_object_key, stage="download")
        log.info("import_module_zip_job: downloading from s3 key=%s -> %s", s3_object_key, str(zip_path))

        try:
            s3.head_object(Bucket=settings.s3_bucket, Key=s3_object_key)
        except ClientError as e:
            code = str((e.response or {}).get("Error", {}).get("Code") or "")
            status = int((e.response or {}).get("ResponseMetadata", {}).get("HTTPStatusCode") or 0)
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                err = FileNotFoundError(f"s3 object not found: {s3_object_key}")
                _set_job_stage(stage="failed", detail=str(err))
                _set_job_error(
                    error=err,
                    error_code="IMPORT_SOURCE_ZIP_NOT_FOUND",
                    error_hint=(
                        "Исходный ZIP не найден в S3. Возможные причины: загрузка не завершилась, "
                        "ключ объекта неверный, либо файл был удалён TTL-cleanup. Попробуйте загрузить ZIP заново."
                    ),
                )
                raise err
            raise

        _download_zip_with_retry(object_key=s3_object_key, dest_path=zip_path)

        _cancel_checkpoint(s3_object_key=s3_object_key, stage="download")

        sha256 = ""
        try:
            h = hashlib.sha256()
            with zip_path.open("rb") as rf:
                while True:
                    _cancel_checkpoint(s3_object_key=s3_object_key, stage="sha256")
                    chunk = rf.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            sha256 = h.hexdigest()
        except Exception:
            sha256 = ""

        if sha256:
            # Hard idempotency: if the same ZIP content was already imported, reuse it.
            try:
                r = get_redis()
                existing_mid = str(r.get(f"admin:import_zip_sha256_to_module_id:{sha256}") or "").strip()
            except Exception:
                existing_mid = ""

            if existing_mid:
                # If we created a stub module for this job, delete it to avoid clutter.
                try:
                    stub_mid = str(module_id or "").strip()
                    if stub_mid and stub_mid != existing_mid:
                        db0 = SessionLocal()
                        try:
                            try:
                                stub_uuid = uuid.UUID(stub_mid)
                            except Exception:
                                stub_uuid = None

                            if stub_uuid is not None:
                                sm = db0.scalar(select(Module).where(Module.id == stub_uuid))
                            else:
                                sm = None

                            if sm is not None:
                                fq = getattr(sm, "final_quiz_id", None)
                                try:
                                    db0.execute(text("DELETE FROM modules WHERE id = :mid"), {"mid": str(sm.id)})
                                except Exception:
                                    try:
                                        db0.delete(sm)
                                    except Exception:
                                        pass
                                if fq is not None:
                                    try:
                                        db0.execute(text("DELETE FROM quizzes WHERE id = :qid"), {"qid": str(fq)})
                                    except Exception:
                                        try:
                                            qx = db0.scalar(select(Quiz).where(Quiz.id == fq))
                                            if qx is not None:
                                                db0.delete(qx)
                                        except Exception:
                                            pass
                                try:
                                    db0.commit()
                                except Exception:
                                    db0.rollback()
                        finally:
                            db0.close()
                except Exception:
                    pass

                regen_job_id: str | None = None
                if enqueue_regen:
                    try:
                        _cancel_checkpoint(s3_object_key=s3_object_key, stage="regen_enqueue")
                        _set_job_stage(stage="regen_enqueue", detail=f"{existing_mid} (reused)")

                        regen_queue_name = str(settings.rq_queue_regen or "").strip() or "corelms_regen"
                        import_queue_name = str(settings.rq_queue_import or "").strip() or "corelms_import"
                        if regen_queue_name == import_queue_name:
                            regen_queue_name = "corelms_regen"

                        q = get_queue(regen_queue_name)
                        regen_job = q.enqueue(
                            regenerate_module_quizzes_job,
                            module_id=str(existing_mid),
                            target_questions=5,
                            job_timeout=60 * 60 * 2,
                            result_ttl=60 * 60 * 24 * 7,
                            failure_ttl=60 * 60 * 24 * 7,
                        )

                        regen_job_id = str(regen_job.id)
                        _set_existing_regen_job_id(module_id=str(existing_mid), regen_job_id=str(regen_job_id))

                        try:
                            meta = dict(regen_job.meta or {})
                            meta["job_kind"] = "regen"
                            meta["module_id"] = str(existing_mid)
                            meta["target_questions"] = 5
                            meta["actor_user_id"] = str(actor_user_id or "")
                            meta["source"] = "auto_after_import"
                            regen_job.meta = meta
                            regen_job.save_meta()
                        except Exception:
                            pass

                        try:
                            job = get_current_job()
                        except Exception:
                            job = None
                        if job is not None:
                            try:
                                jm = dict(job.meta or {})
                                jm["regen_job_id"] = str(regen_job_id)
                                job.meta = jm
                                job.save_meta()
                            except Exception:
                                pass

                        try:
                            r = get_redis()
                            meta = {
                                "job_id": regen_job_id,
                                "module_id": str(existing_mid),
                                "module_title": "",
                                "target_questions": 5,
                                "created_at": datetime.utcnow().isoformat(),
                                "actor_user_id": str(actor_user_id or ""),
                                "source": "auto_after_import",
                            }
                            r.lpush("admin:regen_jobs", json.dumps(meta, ensure_ascii=False))
                            r.ltrim("admin:regen_jobs", 0, 49)
                            r.expire("admin:regen_jobs", 60 * 60 * 24 * 30)
                            r.publish("admin:jobs:changed", str(regen_job_id))
                        except Exception:
                            pass
                    except Exception:
                        regen_job_id = None

                _set_job_stage(stage="done", detail=f"reused: {existing_mid}")
                _release_enqueue_locks()
                return {
                    "ok": True,
                    "module_id": str(existing_mid),
                    "reused": True,
                    "zip_sha256": sha256,
                    "regen_job_id": regen_job_id,
                }

        size = None
        try:
            size = int(zip_path.stat().st_size)
        except Exception:
            size = None

        log.info("import_module_zip_job: download done bytes=%s", size)

        _set_job_stage(stage="extract")
        _cancel_checkpoint(s3_object_key=s3_object_key, stage="extract")
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            log.info("import_module_zip_job: extracting zip to %s", str(base))
            _job_heartbeat(detail="extract: start")
            _safe_extract_zip(zf=zf, dest=base)
            _job_heartbeat(detail="extract: done")
        log.info("import_module_zip_job: extract done")

        _cancel_checkpoint(s3_object_key=s3_object_key, stage="extract")

        inferred_title: str | None = None
        if source_filename:
            inferred_title = re.sub(r"\.zip$", "", str(source_filename).strip(), flags=re.IGNORECASE).strip() or None

        # Determine module root folder.
        # Real-world ZIPs may contain:
        # - a single wrapping folder (ideal)
        # - a flat root (files directly in root)
        # - multiple top-level entries including __MACOSX
        # Prefer a folder that matches the inferred title (from filename) when present.
        top_dirs = [p for p in base.iterdir() if p.is_dir() and p.name not in {"__MACOSX"}]
        top_files = [p for p in base.iterdir() if p.is_file() and p.name not in {"__MACOSX"}]
        module_dir = None
        if len(top_dirs) == 1 and not top_files:
            module_dir = top_dirs[0]
        elif inferred_title:
            tnorm = str(inferred_title).strip().casefold()
            for d in top_dirs:
                if str(d.name or "").strip().casefold() == tnorm:
                    module_dir = d
                    break
        if module_dir is None:
            module_dir = base

        # Fail early if ZIP extracted to nothing useful.
        try:
            any_entries = any(True for _ in module_dir.iterdir())
        except Exception:
            any_entries = False
        if not any_entries:
            err = ValueError("zip extracted to empty directory")
            _set_job_stage(stage="failed", detail=str(err))
            _set_job_error(
                error=err,
                error_code="ZIP_EMPTY",
                error_hint="ZIP пустой или содержит только служебные папки. Проверьте содержимое архива.",
            )
            raise err

        try:
            _set_job_stage(stage="extract", detail=f"module_dir: {str(module_dir)}")
        except Exception:
            pass
        log.info("import_module_zip_job: module_dir=%s", str(module_dir))

        db = SessionLocal()
        try:
            report: dict[str, object] = {}
            _set_job_stage(stage="import")
            _cancel_checkpoint(s3_object_key=s3_object_key, stage="import")
            log.info("import_module_zip_job: importing to DB")
            _job_heartbeat(detail="import: start")
            mid = import_module_from_dir(
                db=db,
                module_dir=module_dir,
                title_override=(title or inferred_title),
                report_out=report,
                generate_questions=False,
                module_id_override=(str(module_id).strip() or None),
            )

            # Canonical linkage: bind the imported module to its source ZIP key.
            # This makes /admin/storage/objects filtering authoritative by DB,
            # and keeps the system consistent across Redis resets.
            try:
                m = db.scalar(select(Module).where(Module.id == mid))
            except Exception:
                m = None
            if m is not None:
                try:
                    if str(s3_object_key or "").strip():
                        m.import_object_key = str(s3_object_key).strip()
                    # Ensure storage_prefix exists (normally set by importer).
                    if not str(getattr(m, "storage_prefix", "") or "").strip():
                        safe = _slugify_s3_segment(str(getattr(m, "title", "") or "module"))
                        m.storage_prefix = f"modules/{safe}__{str(m.id)}/"
                    db.add(m)
                    db.flush()
                except Exception:
                    pass

            module_title_for_meta = ""
            try:
                if m is not None:
                    module_title_for_meta = str(getattr(m, "title", "") or "").strip()
            except Exception:
                module_title_for_meta = ""

            try:
                job = get_current_job()
            except Exception:
                job = None
            if job is not None:
                try:
                    jm = dict(job.meta or {})
                    jm["module_id"] = str(mid)
                    job.meta = jm
                    job.save_meta()
                except Exception:
                    pass
            _job_heartbeat(detail="import: done")

            _set_job_stage(stage="commit")
            _cancel_checkpoint(s3_object_key=s3_object_key, stage="commit")
            db.commit()
            log.info("import_module_zip_job: commit done module_id=%s", str(mid))

            # Persist ZIP-content idempotency mapping.
            if sha256:
                try:
                    r = get_redis()
                    r.set(f"admin:import_zip_sha256_to_module_id:{sha256}", str(mid))
                    r.expire(f"admin:import_zip_sha256_to_module_id:{sha256}", 60 * 60 * 24 * 30)
                    r.set(f"admin:import_zip_sha256_by_module_id:{str(mid)}", sha256)
                    r.expire(f"admin:import_zip_sha256_by_module_id:{str(mid)}", 60 * 60 * 24 * 30)
                except Exception:
                    pass

            # If cancellation was requested right after commit, stop before any follow-up actions.
            _cancel_checkpoint(s3_object_key=s3_object_key, stage="post_commit")

            _set_job_stage(stage="cleanup", detail=s3_object_key)
            _cancel_checkpoint(s3_object_key=s3_object_key, stage="cleanup")
            cleanup_done = True
            report["source_zip_deleted"] = False
            report["source_zip_kept"] = True

            regen_job_id: str | None = None
            if enqueue_regen:
                existing_regen_job_id = _get_existing_regen_job_id(module_id=str(mid))
                if existing_regen_job_id:
                    regen_job_id = existing_regen_job_id
                else:
                    last_err: Exception | None = None
                    for attempt in range(1, 4):
                        try:
                            _cancel_checkpoint(s3_object_key=s3_object_key, stage="regen_enqueue")
                            _set_job_stage(stage="regen_enqueue", detail=f"{mid} (attempt {attempt}/3)")

                            regen_queue_name = str(settings.rq_queue_regen or "").strip() or "corelms_regen"
                            import_queue_name = str(settings.rq_queue_import or "").strip() or "corelms_import"
                            if regen_queue_name == import_queue_name:
                                regen_queue_name = "corelms_regen"
                            log.info(
                                "import_module_zip_job: enqueue regen module_id=%s queue=%s (import_queue=%s)",
                                str(mid),
                                regen_queue_name,
                                import_queue_name,
                            )

                            q = get_queue(regen_queue_name)
                            regen_job = q.enqueue(
                                regenerate_module_quizzes_job,
                                module_id=str(mid),
                                target_questions=5,
                                job_timeout=60 * 60 * 2,
                                result_ttl=60 * 60 * 24 * 7,
                                failure_ttl=60 * 60 * 24 * 7,
                            )

                            regen_job_id = str(regen_job.id)
                            _set_existing_regen_job_id(module_id=str(mid), regen_job_id=str(regen_job_id))

                            try:
                                meta = dict(regen_job.meta or {})
                                meta["job_kind"] = "regen"
                                meta["module_id"] = str(mid)
                                meta["module_title"] = module_title_for_meta or str(report.get("module_title") or "")
                                meta["target_questions"] = 5
                                meta["actor_user_id"] = str(actor_user_id or "")
                                meta["source"] = "auto_after_import"
                                regen_job.meta = meta
                                regen_job.save_meta()
                            except Exception:
                                pass

                            # Store regen_job_id in import job meta for easier UI linking.
                            try:
                                job = get_current_job()
                            except Exception:
                                job = None
                            if job is not None:
                                try:
                                    jm = dict(job.meta or {})
                                    jm["regen_job_id"] = str(regen_job_id)
                                    job.meta = jm
                                    job.save_meta()
                                except Exception:
                                    pass

                            try:
                                r = get_redis()
                                meta = {
                                    "job_id": regen_job_id,
                                    "module_id": str(mid),
                                    "module_title": module_title_for_meta or str(report.get("module_title") or ""),
                                    "target_questions": 5,
                                    "created_at": datetime.utcnow().isoformat(),
                                    "actor_user_id": str(actor_user_id or ""),
                                    "source": "auto_after_import",
                                }
                                r.lpush("admin:regen_jobs", json.dumps(meta, ensure_ascii=False))
                                r.ltrim("admin:regen_jobs", 0, 49)
                                r.expire("admin:regen_jobs", 60 * 60 * 24 * 30)
                                r.publish("admin:jobs:changed", str(regen_job_id))
                            except Exception:
                                pass

                            last_err = None
                            break
                        except Exception as e:
                            last_err = e
                            try:
                                time.sleep(0.5)
                            except Exception:
                                pass

                    if last_err is not None or not regen_job_id:
                        report["regen_enqueue_error"] = str(last_err)
                        _set_job_stage(stage="failed", detail="regen enqueue failed")
                        _set_job_error(
                            error=last_err,
                            error_code="REGEN_ENQUEUE_FAILED",
                            error_hint=(
                                "Импорт завершился, но не удалось поставить задачу регена в очередь. "
                                "Проверьте Redis/RQ worker/очередь 'corelms_regen'."
                            ),
                        )
                        raise last_err

            report["regen_job_id"] = regen_job_id

            _set_job_stage(stage="done", detail=str(mid))
            _release_enqueue_locks()
            return {"ok": True, "module_id": str(mid), "report": report, "regen_job_id": regen_job_id}
        except ImportCanceledError as e:
            try:
                db.rollback()
            except Exception:
                pass
            try:
                if not cleanup_done:
                    _cleanup_uploaded_keys_best_effort()
            except Exception:
                pass
            _release_enqueue_locks()
            return {"ok": False, "canceled": True}
        except Exception as e:
            _set_job_stage(stage="failed", detail=str(e))
            _set_job_error(error=e)
            log.exception("import_module_zip_job: failed")
            db.rollback()
            try:
                if not cleanup_done:
                    _cleanup_uploaded_keys_best_effort()
            except Exception:
                pass
            _release_enqueue_locks()
            raise
        finally:
            db.close()
