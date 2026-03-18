from __future__ import annotations

import logging
import pathlib
import random
import re
import subprocess
import tempfile
import time
import uuid

from botocore.exceptions import ClientError
from rq import get_current_job
from sqlalchemy import select

from app.core.config import settings
from app.core.redis_client import get_redis
from app.db.session import SessionLocal
from app.models.asset import ContentAsset
from app.services.storage import ensure_bucket_exists, get_s3_client


log = logging.getLogger(__name__)


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


class TranscodeCanceledError(RuntimeError):
    pass


def _cancel_checkpoint(stage: str) -> None:
    if not _is_cancel_requested():
        return
    raise TranscodeCanceledError(f"cancel at {stage}")


def _snip(s: object, limit: int = 2000) -> str:
    try:
        v = str(s or "")
    except Exception:
        return ""
    v = v.strip()
    if not v:
        return ""
    if limit and len(v) > int(limit):
        return v[: int(limit)] + "…"
    return v


def _normalize_mp4_object_key(object_key: str) -> str:
    k = str(object_key or "").strip()
    if not k:
        return k
    if re.search(r"\.mp4$", k, flags=re.IGNORECASE):
        return k
    return re.sub(r"\.[A-Za-z0-9]{1,8}$", ".mp4", k) if "." in k else (k + ".mp4")


def _normalize_mp4_filename(name: str) -> str:
    n = str(name or "").strip() or "video"
    if re.search(r"\.mp4$", n, flags=re.IGNORECASE):
        return n
    return re.sub(r"\.[A-Za-z0-9]{1,8}$", ".mp4", n) if "." in n else (n + ".mp4")


def _needs_transcode(asset: ContentAsset) -> bool:
    name = str(getattr(asset, "original_filename", "") or "").strip().lower()
    key = str(getattr(asset, "object_key", "") or "").strip().lower()
    ct = str(getattr(asset, "mime_type", "") or "").strip().lower()

    if name.endswith(".mp4") or key.endswith(".mp4"):
        return False
    if ct == "video/mp4":
        return False

    ext = ""
    for s in (name, key):
        if "." in s:
            ext = s.rsplit(".", 1)[-1].strip()
            if ext:
                break

    transcode_exts = {"mov", "mkv", "avi", "wmv", "flv", "mpg", "mpeg", "mts", "m2ts"}
    if ext in transcode_exts:
        return True

    if ct.startswith("video/") and ("quicktime" in ct or "x-matroska" in ct or "x-msvideo" in ct):
        return True

    return False


def _unique_object_key(*, s3, desired_key: str) -> str:
    k = str(desired_key or "").strip()
    if not k:
        return k

    def exists(key: str) -> bool:
        try:
            s3.head_object(Bucket=settings.s3_bucket, Key=key)
            return True
        except ClientError as e:
            code = str((e.response or {}).get("Error", {}).get("Code") or "").strip()
            status = int((e.response or {}).get("ResponseMetadata", {}).get("HTTPStatusCode") or 0)
            if code in {"NoSuchKey", "NotFound"} or status == 404:
                return False
            raise

    if not exists(k):
        return k

    base = k
    stem = base
    if "." in base:
        stem = base.rsplit(".", 1)[0]
    for i in range(1, 50):
        alt = f"{stem}.t{i}.mp4"
        if not exists(alt):
            return alt
    return f"{stem}.t{int(time.time())}.mp4"


def _download_to_path(*, s3, object_key: str, dest: pathlib.Path) -> None:
    tries = 4
    base = 0.6
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        _cancel_checkpoint("download")
        try:
            if dest.exists():
                dest.unlink(missing_ok=True)
            with dest.open("wb") as f:
                s3.download_fileobj(settings.s3_bucket, object_key, f)
            return
        except TranscodeCanceledError:
            raise
        except Exception as e:
            last = e
            if attempt >= tries:
                raise
            try:
                time.sleep(base * (2 ** (attempt - 1)) + random.random() * 0.25)
            except Exception:
                pass
    if last is not None:
        raise last


def _transcode_to_mp4(*, input_path: pathlib.Path, output_path: pathlib.Path) -> tuple[bool, str]:
    _cancel_checkpoint("ffmpeg")
    timeout_s = int(getattr(settings, "import_transcode_timeout_seconds", 0) or 0) or 60 * 45
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        if proc.returncode != 0:
            return False, _snip(proc.stderr, 2000)
    except Exception as e:
        return False, _snip(e, 2000)

    try:
        if not output_path.exists() or int(output_path.stat().st_size) <= 0:
            return False, "empty_output"
    except Exception:
        return False, "bad_output"

    return True, ""


def transcode_all_videos_job(*, limit: int = 5000, delete_original: bool = True) -> dict:
    ensure_bucket_exists()
    s3 = get_s3_client()

    try:
        job = get_current_job()
    except Exception:
        job = None

    report: dict[str, object] = {
        "ok": True,
        "limit": int(max(1, min(int(limit or 5000), 20000))),
        "scanned": 0,
        "candidates": 0,
        "transcoded": 0,
        "skipped": 0,
        "errors": 0,
        "deleted_original": 0,
        "bytes_in": 0,
        "bytes_out": 0,
        "last_error": "",
    }

    db = SessionLocal()
    try:
        rows = db.scalars(select(ContentAsset).order_by(ContentAsset.created_at.desc()).limit(int(report["limit"]))).all()
        for a in rows:
            _cancel_checkpoint("loop")
            report["scanned"] = int(report.get("scanned") or 0) + 1

            if not _needs_transcode(a):
                report["skipped"] = int(report.get("skipped") or 0) + 1
                continue

            report["candidates"] = int(report.get("candidates") or 0) + 1

            old_key = str(a.object_key or "").strip()
            if not old_key:
                report["errors"] = int(report.get("errors") or 0) + 1
                continue

            tmpdir = tempfile.mkdtemp(prefix="corelms_transcode_batch_")
            tmp_base = pathlib.Path(tmpdir)
            in_path = tmp_base / "in"
            out_path = tmp_base / "out.mp4"

            try:
                if job is not None:
                    meta = dict(job.meta or {})
                    meta.setdefault("job_kind", "import")
                    meta["stage"] = "transcode"
                    meta["detail"] = f"{a.original_filename}"
                    meta["asset_id"] = str(a.id)
                    meta["object_key"] = old_key
                    job.meta = meta
                    job.save_meta()

                _download_to_path(s3=s3, object_key=old_key, dest=in_path)
                try:
                    report["bytes_in"] = int(report.get("bytes_in") or 0) + int(in_path.stat().st_size)
                except Exception:
                    pass

                ok, err = _transcode_to_mp4(input_path=in_path, output_path=out_path)
                if not ok:
                    report["errors"] = int(report.get("errors") or 0) + 1
                    report["last_error"] = str(err or "")
                    continue

                try:
                    report["bytes_out"] = int(report.get("bytes_out") or 0) + int(out_path.stat().st_size)
                except Exception:
                    pass

                new_key_desired = _normalize_mp4_object_key(old_key)
                new_key = _unique_object_key(s3=s3, desired_key=new_key_desired)
                new_name = _normalize_mp4_filename(str(a.original_filename or ""))

                with out_path.open("rb") as f:
                    s3.put_object(
                        Bucket=settings.s3_bucket,
                        Key=new_key,
                        Body=f,
                        ContentType="video/mp4",
                    )

                a.object_key = new_key
                a.original_filename = new_name
                a.mime_type = "video/mp4"
                try:
                    a.size_bytes = int(out_path.stat().st_size)
                except Exception:
                    pass
                try:
                    a.version = int(getattr(a, "version", 1) or 1) + 1
                except Exception:
                    pass

                db.add(a)
                db.commit()

                if delete_original and new_key != old_key:
                    try:
                        s3.delete_object(Bucket=settings.s3_bucket, Key=old_key)
                        report["deleted_original"] = int(report.get("deleted_original") or 0) + 1
                    except Exception:
                        pass

                report["transcoded"] = int(report.get("transcoded") or 0) + 1
            except TranscodeCanceledError:
                raise
            except Exception as e:
                try:
                    db.rollback()
                except Exception:
                    pass
                report["errors"] = int(report.get("errors") or 0) + 1
                report["last_error"] = _snip(e, 2000)
            finally:
                try:
                    in_path.unlink(missing_ok=True)
                except Exception:
                    pass
                try:
                    out_path.unlink(missing_ok=True)
                except Exception:
                    pass
                try:
                    tmp_base.rmdir()
                except Exception:
                    pass

        try:
            remaining = 0
            for a in db.scalars(select(ContentAsset)).all():
                if _needs_transcode(a):
                    remaining += 1
        except Exception:
            remaining = None  # type: ignore

        report["finished"] = False if remaining is None else (int(remaining) == 0)
        report["remaining_candidates_estimate"] = remaining

        if job is not None:
            try:
                meta = dict(job.meta or {})
                meta.update(report)
                job.meta = meta
                job.save_meta()
            except Exception:
                pass

        return report
    except TranscodeCanceledError:
        try:
            db.rollback()
        except Exception:
            pass
        return {"ok": False, "canceled": True, **report}
    finally:
        db.close()


def enqueue_transcode_all_videos_job(*, actor_user_id: str | None = None, limit: int = 5000) -> str:
    try:
        r = get_redis()
        r.set("admin:transcode:last_request", str(time.time()))
        r.expire("admin:transcode:last_request", 60 * 60 * 24)
    except Exception:
        pass

    return ""  # placeholder to keep api shape stable if needed
