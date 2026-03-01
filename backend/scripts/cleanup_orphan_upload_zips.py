from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import uuid

from sqlalchemy import select

# Ensure imports work when running from any CWD (Windows / local) and in Docker (/app)
_HERE = pathlib.Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, "/app")
sys.path.insert(0, os.getcwd())

from app.core.config import settings
from app.core.redis_client import get_redis
from app.db.session import SessionLocal
from app.models.module import Module
from app.services.storage import ensure_bucket_exists, get_s3_client


def _iter_upload_zip_objects(*, prefix: str) -> list[dict[str, object]]:
    ensure_bucket_exists()
    s3 = get_s3_client()

    token: str | None = None
    out: list[dict[str, object]] = []
    while True:
        kwargs: dict[str, object] = {
            "Bucket": settings.s3_bucket,
            "Prefix": prefix,
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token

        resp = s3.list_objects_v2(**kwargs)
        contents = resp.get("Contents") or []
        for it in contents:
            try:
                key = str((it or {}).get("Key") or "").strip()
                if not key:
                    continue
                if not key.lower().endswith(".zip"):
                    continue
                out.append(
                    {
                        "key": key,
                        "size": int((it or {}).get("Size") or 0),
                        "last_modified": (it or {}).get("LastModified"),
                    }
                )
            except Exception:
                continue

        if not resp.get("IsTruncated"):
            break
        token = str(resp.get("NextContinuationToken") or "") or None
        if not token:
            break

    return out


def _collect_used_object_keys(*, include_enqueued: bool = True) -> tuple[set[str], dict[str, object]]:
    dbg: dict[str, object] = {"queue_used": 0, "redis_mapping_used": 0, "stale_mappings_deleted": 0}
    used: set[str] = set()

    try:
        r = get_redis()
    except Exception:
        return used, {"error": "redis unavailable"}

    # Active queue jobs
    try:
        raw = r.lrange("admin:import_jobs", 0, 1000)
    except Exception:
        raw = []

    for s in list(raw or []):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                k = str(obj.get("object_key") or "").strip()
                if k:
                    used.add(k)
        except Exception:
            continue

    dbg["queue_used"] = int(len(used))

    if include_enqueued:
        try:
            enq = 0
            for key in r.scan_iter(match="admin:import_enqueued_by_object_key:*"):
                try:
                    ks = key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else str(key)
                    obj_key = ks.split("admin:import_enqueued_by_object_key:", 1)[-1]
                    obj_key = str(obj_key or "").strip()
                    if obj_key:
                        used.add(obj_key)
                        enq += 1
                except Exception:
                    continue
            dbg["enqueued_by_object_key_used"] = int(enq)
        except Exception:
            dbg["enqueued_by_object_key_used"] = 0

    # Redis reverse mapping for existing modules
    mapped_mids: list[str] = []
    try:
        for key in r.scan_iter(match="admin:import_object_key_by_module_id:*"):
            try:
                ks = key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else str(key)
                mid = ks.split(":")[-1]
                if mid:
                    mapped_mids.append(mid)
            except Exception:
                continue
    except Exception:
        mapped_mids = []

    existing_mids: set[str] = set()
    mids_uuid: list[uuid.UUID] = []
    for mid in mapped_mids:
        try:
            mids_uuid.append(uuid.UUID(str(mid)))
        except Exception:
            continue

    if mids_uuid:
        with SessionLocal() as db:
            try:
                rows = db.scalars(select(Module.id).where(Module.id.in_(mids_uuid))).all()
                existing_mids = {str(x) for x in (rows or []) if x is not None}
            except Exception:
                existing_mids = set()

    stale_deleted = 0
    mapped_used = 0

    for mid in mapped_mids:
        if mid not in existing_mids:
            try:
                r.delete(f"admin:import_object_key_by_module_id:{mid}")
                stale_deleted += 1
            except Exception:
                pass
            continue

        try:
            ok = str(r.get(f"admin:import_object_key_by_module_id:{mid}") or "").strip()
            if ok:
                used.add(ok)
                mapped_used += 1
        except Exception:
            continue

    dbg["redis_mapping_used"] = int(mapped_used)
    dbg["stale_mappings_deleted"] = int(stale_deleted)

    return used, dbg


def main() -> int:
    ap = argparse.ArgumentParser(description="Cleanup orphan uploads/*.zip objects in S3 (dry-run by default).")
    ap.add_argument("--prefix", default="uploads/", help="S3 prefix to scan (default: uploads/)")
    ap.add_argument("--dry-run", action="store_true", help="Only print what would be deleted")
    ap.add_argument("--delete", action="store_true", help="Actually delete orphan zip objects")
    ap.add_argument(
        "--include-enqueued",
        action="store_true",
        default=True,
        help="Treat admin:import_enqueued_by_object_key:* as used (default: true)",
    )
    ap.add_argument(
        "--ttl-hours",
        type=int,
        default=72,
        help="Delete only objects older than this TTL in hours (default: 72). Set 0 to disable age guard.",
    )
    ap.add_argument("--max", type=int, default=0, help="Max objects to delete (0 = no limit)")
    args = ap.parse_args()

    # Default behavior: dry-run unless --delete was passed.
    if not args.delete:
        args.dry_run = True

    used, dbg = _collect_used_object_keys(include_enqueued=bool(args.include_enqueued))
    objs = _iter_upload_zip_objects(prefix=str(args.prefix or "uploads/").strip().lstrip("/"))

    ttl_hours = int(args.ttl_hours or 0)
    orphans: list[dict[str, object]] = []
    for o in objs:
        k = str(o.get("key") or "").strip()
        if not k or k in used:
            continue
        if ttl_hours > 0:
            lm = o.get("last_modified")
            try:
                from datetime import datetime, timedelta, timezone

                if isinstance(lm, datetime):
                    if lm.tzinfo is None:
                        lm = lm.replace(tzinfo=timezone.utc)
                    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
                    if lm > cutoff:
                        continue
            except Exception:
                continue
        orphans.append(o)
    orphans.sort(key=lambda x: str(x.get("key") or ""))

    if args.max and args.max > 0:
        orphans = orphans[: int(args.max)]

    print(f"bucket={settings.s3_bucket}")
    print(f"prefix={args.prefix}")
    print(f"found_zip_objects={len(objs)}")
    print(f"used_keys={len(used)}")
    print(f"orphans={len(orphans)}")
    print(f"debug={dbg}")
    print(f"ttl_hours={ttl_hours}")

    for o in orphans:
        print(f"ORPHAN\t{o.get('key')}\t{o.get('size')}\t{o.get('last_modified')}")

    if args.dry_run or not args.delete or not orphans:
        return 0

    ensure_bucket_exists()
    s3 = get_s3_client()

    deleted = 0
    for i in range(0, len(orphans), 1000):
        batch = orphans[i : i + 1000]
        to_delete = [{"Key": str(x.get("key") or "").strip()} for x in batch if str(x.get("key") or "").strip()]
        if not to_delete:
            continue
        try:
            s3.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": to_delete, "Quiet": True})
            deleted += len(to_delete)
        except Exception:
            print(f"FAILED_DELETE_BATCH size={len(to_delete)}")

    print(f"deleted={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
