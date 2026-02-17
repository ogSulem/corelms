from __future__ import annotations

import pathlib
import tempfile
import zipfile
import shutil
from datetime import datetime

import re
import logging

from rq import get_current_job

from botocore.exceptions import ClientError

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.module_importer import import_module_from_dir
from app.services.quiz_regeneration_jobs import regenerate_module_quizzes_job
from app.services.storage import ensure_bucket_exists, get_s3_client
from app.core.queue import get_queue
from app.core.redis_client import get_redis


log = logging.getLogger(__name__)


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
        job.meta = meta
        job.save_meta()
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
            elif "module title already exists" in msg.lower() or "title already exists" in msg.lower():
                code = "DUPLICATE_MODULE_TITLE"
                if not hint:
                    hint = "Смените название модуля (или удалите существующий модуль с таким названием)."
            elif "failed to upload zip" in msg.lower() or "failed to enqueue" in msg.lower():
                code = "IMPORT_QUEUE_OR_UPLOAD_FAILED"
                if not hint:
                    hint = "Проверьте доступность Redis/worker и MinIO/S3."

        meta["error_code"] = code
        meta["error_class"] = cls
        meta["error_message"] = msg
        if hint:
            meta["error_hint"] = hint
        job.meta = meta
        job.save_meta()
    except Exception:
        return


def _safe_extract_zip(*, zf: zipfile.ZipFile, dest: pathlib.Path) -> None:
    dest = dest.resolve()
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
    enqueue_regen: bool = True,
) -> dict:
    print(f"import_module_zip_job: start s3_object_key={s3_object_key} source_filename={source_filename} title={title}", flush=True)
    log.info("import_module_zip_job: start s3_object_key=%s source_filename=%s title=%s", s3_object_key, source_filename, title)
    _set_job_stage(stage="start", detail=s3_object_key)
    ensure_bucket_exists()
    s3 = get_s3_client()

    cleanup_done = False

    _cancel_checkpoint(s3_object_key=s3_object_key, stage="start")

    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)
        zip_path = base / "module.zip"

        _set_job_stage(stage="download", detail=s3_object_key)
        _cancel_checkpoint(s3_object_key=s3_object_key, stage="download")
        print(f"import_module_zip_job: downloading from minio key={s3_object_key} -> {str(zip_path)}", flush=True)
        log.info("import_module_zip_job: downloading from minio key=%s -> %s", s3_object_key, str(zip_path))

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
                        "Исходный ZIP не найден в S3/MinIO. Возможные причины: загрузка не завершилась, "
                        "ключ объекта неверный, либо файл был удалён TTL-cleanup. Попробуйте загрузить ZIP заново."
                    ),
                )
                raise err
            raise
        with zip_path.open("wb") as f:
            s3.download_fileobj(settings.s3_bucket, s3_object_key, f)

        _cancel_checkpoint(s3_object_key=s3_object_key, stage="download")

        size = None
        try:
            size = int(zip_path.stat().st_size)
        except Exception:
            size = None

        print(f"import_module_zip_job: download done bytes={size if size is not None else 'unknown'}", flush=True)
        log.info("import_module_zip_job: download done bytes=%s", size)

        _set_job_stage(stage="extract")
        _cancel_checkpoint(s3_object_key=s3_object_key, stage="extract")
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            print(f"import_module_zip_job: extracting zip to {str(base)}", flush=True)
            log.info("import_module_zip_job: extracting zip to %s", str(base))
            _safe_extract_zip(zf=zf, dest=base)
        print("import_module_zip_job: extract done", flush=True)
        log.info("import_module_zip_job: extract done")

        _cancel_checkpoint(s3_object_key=s3_object_key, stage="extract")

        dirs = [p for p in base.iterdir() if p.is_dir() and p.name not in {"__MACOSX"}]
        module_dir = dirs[0] if len(dirs) == 1 else base
        print(f"import_module_zip_job: module_dir={str(module_dir)}", flush=True)
        log.info("import_module_zip_job: module_dir=%s", str(module_dir))

        inferred_title: str | None = None
        if source_filename:
            inferred_title = re.sub(r"\.zip$", "", str(source_filename).strip(), flags=re.IGNORECASE).strip() or None

        db = SessionLocal()
        try:
            report: dict[str, object] = {}
            _set_job_stage(stage="import")
            _cancel_checkpoint(s3_object_key=s3_object_key, stage="import")
            print("import_module_zip_job: importing to DB", flush=True)
            log.info("import_module_zip_job: importing to DB")
            mid = import_module_from_dir(
                db=db,
                module_dir=module_dir,
                title_override=(title or inferred_title),
                report_out=report,
                generate_questions=False,
            )

            _set_job_stage(stage="commit")
            _cancel_checkpoint(s3_object_key=s3_object_key, stage="commit")
            db.commit()
            print(f"import_module_zip_job: commit done module_id={str(mid)}", flush=True)
            log.info("import_module_zip_job: commit done module_id=%s", str(mid))

            _set_job_stage(stage="cleanup", detail=s3_object_key)
            _cancel_checkpoint(s3_object_key=s3_object_key, stage="cleanup")
            cleanup_done = True
            report["source_zip_deleted"] = False
            report["source_zip_kept"] = True

            regen_job_id: str | None = None
            if enqueue_regen:
                try:
                    _set_job_stage(stage="regen_enqueue", detail=str(mid))
                    q = get_queue("corelms")
                    regen_job = q.enqueue(
                        regenerate_module_quizzes_job,
                        module_id=str(mid),
                        target_questions=5,
                        job_timeout=60 * 60 * 2,
                        result_ttl=60 * 60 * 24,
                        failure_ttl=60 * 60 * 24,
                    )
                    regen_job_id = str(regen_job.id)
                    try:
                        r = get_redis()
                        meta = {
                            "job_id": regen_job_id,
                            "module_id": str(mid),
                            "module_title": str(report.get("module_title") or ""),
                            "target_questions": 5,
                            "created_at": datetime.utcnow().isoformat(),
                            "actor_user_id": str(actor_user_id or ""),
                            "source": "auto_after_import",
                        }
                        r.lpush("admin:regen_jobs", json.dumps(meta, ensure_ascii=False))
                        r.ltrim("admin:regen_jobs", 0, 49)
                        r.expire("admin:regen_jobs", 60 * 60 * 24 * 30)
                    except Exception:
                        pass
                except Exception as e:
                    report["regen_enqueue_error"] = str(e)
                    regen_job_id = None

            report["regen_job_id"] = regen_job_id

            _set_job_stage(stage="done", detail=str(mid))
            return {"ok": True, "module_id": str(mid), "report": report, "regen_job_id": regen_job_id}
        except ImportCanceledError as e:
            try:
                db.rollback()
            except Exception:
                pass
            return {"ok": False, "canceled": True}
        except Exception as e:
            _set_job_stage(stage="failed", detail=str(e))
            _set_job_error(error=e)
            print(f"import_module_zip_job: failed err={e}", flush=True)
            log.exception("import_module_zip_job: failed")
            db.rollback()
            raise
        finally:
            db.close()
