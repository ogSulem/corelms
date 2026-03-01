from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import httpx

# Ensure imports work when running from any CWD (Windows / local) and in Docker (/app)
_HERE = pathlib.Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, "/app")
sys.path.insert(0, os.getcwd())

from app.core.config import settings
from app.services.storage import ensure_bucket_exists, get_s3_client


def _slugify_s3_segment(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"\.zip$", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-_.]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-.")
    return (s[:80] or "module")


def _canonical_upload_key(title: str) -> str:
    safe = _slugify_s3_segment(title)
    return f"uploads/{safe}/{safe}.zip"


def _legacy_upload_key(title: str) -> str:
    name = str(title or "").strip() or "module"
    if name.lower().endswith(".zip"):
        name = name[: -len(".zip")]
    return f"uploads/{name}.zip"


def _s3_object_exists(*, key: str) -> bool:
    ensure_bucket_exists()
    s3 = get_s3_client()
    try:
        s3.head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except Exception:
        return False


@dataclass
class Item:
    title: str
    url: str


def _read_manifest(path: str) -> list[Item]:
    p = pathlib.Path(path)
    raw = p.read_text(encoding="utf-8", errors="replace")

    items: list[Item] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue

        parts = s.split("\t")
        parts = [x.strip() for x in parts if x.strip()]
        if len(parts) >= 2:
            title = parts[0]
            url = parts[1]
        else:
            parts2 = s.split(" ", 1)
            parts2 = [x.strip() for x in parts2 if x.strip()]
            if len(parts2) < 2:
                raise ValueError(f"Invalid line in manifest: {line}")
            title, url = parts2[0], parts2[1]

        items.append(Item(title=title, url=url))

    return items


def _yadisk_get_public_resource(*, public_url: str, path: str | None = None, limit: int = 200, offset: int = 0) -> dict:
    public_url = str(public_url or "").strip()
    base = "https://cloud-api.yandex.net/v1/disk/public/resources"
    params: dict[str, object] = {
        "public_key": public_url,
        "limit": int(limit or 200),
        "offset": int(offset or 0),
    }
    if path:
        params["path"] = str(path)
    with httpx.Client(timeout=60.0, follow_redirects=True) as c:
        r = c.get(base, params=params)
        r.raise_for_status()
        obj = r.json()
        return obj if isinstance(obj, dict) else {}


def _yadisk_list_root_dirs(*, public_url: str, limit: int = 200) -> list[dict[str, object]]:
    root = _yadisk_get_public_resource(public_url=public_url, path=None, limit=limit, offset=0)
    embedded = root.get("_embedded") if isinstance(root, dict) else None
    items = (embedded or {}).get("items") if isinstance(embedded, dict) else None
    out: list[dict[str, object]] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if str(it.get("type") or "").strip().lower() != "dir":
            continue
        out.append(it)
    return out


def _yadisk_get_download_href(*, public_url: str, path: str) -> str:
    base = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
    params = {"public_key": str(public_url or "").strip(), "path": str(path or "").strip()}
    with httpx.Client(timeout=60.0, follow_redirects=True) as c:
        r = c.get(base, params=params)
        r.raise_for_status()
        obj = r.json()
        if isinstance(obj, dict):
            return str(obj.get("href") or "").strip()
    return ""


def _iter_bytes_from_url(*, url: str, timeout: float) -> Iterable[bytes]:
    with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as r:
        r.raise_for_status()
        for chunk in r.iter_bytes(chunk_size=1024 * 1024):
            if chunk:
                yield chunk


def _upload_stream_to_s3(*, key: str, it: Iterable[bytes], content_type: str = "application/zip") -> tuple[int, str]:
    ensure_bucket_exists()
    s3 = get_s3_client()

    h = hashlib.sha256()
    size = 0

    # True streaming upload: multipart to avoid buffering ZIP on local disk.
    # Use conservative part size to keep memory bounded.
    part_size = 16 * 1024 * 1024
    upload_id = None
    parts: list[dict[str, object]] = []
    buf = bytearray()
    part_number = 1

    resp = s3.create_multipart_upload(Bucket=settings.s3_bucket, Key=key, ContentType=content_type)
    upload_id = str(resp.get("UploadId") or "").strip() or None
    if not upload_id:
        raise RuntimeError("failed to create multipart upload")

    def _flush_part() -> None:
        nonlocal part_number, buf
        if not buf:
            return
        r = s3.upload_part(
            Bucket=settings.s3_bucket,
            Key=key,
            UploadId=upload_id,
            PartNumber=part_number,
            Body=bytes(buf),
        )
        etag = str(r.get("ETag") or "").strip()
        if not etag:
            raise RuntimeError("multipart upload_part missing ETag")
        parts.append({"ETag": etag, "PartNumber": part_number})
        part_number += 1
        buf = bytearray()

    try:
        for chunk in it:
            h.update(chunk)
            size += len(chunk)
            buf.extend(chunk)
            while len(buf) >= part_size:
                take = bytes(buf[:part_size])
                buf = bytearray(buf[part_size:])
                r = s3.upload_part(
                    Bucket=settings.s3_bucket,
                    Key=key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=take,
                )
                etag = str(r.get("ETag") or "").strip()
                if not etag:
                    raise RuntimeError("multipart upload_part missing ETag")
                parts.append({"ETag": etag, "PartNumber": part_number})
                part_number += 1

        _flush_part()

        s3.complete_multipart_upload(
            Bucket=settings.s3_bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )
    except Exception:
        try:
            if upload_id:
                s3.abort_multipart_upload(Bucket=settings.s3_bucket, Key=key, UploadId=upload_id)
        except Exception:
            pass
        raise

    return size, h.hexdigest()


def _load_state(path: str) -> dict[str, object]:
    p = pathlib.Path(path)
    if not p.exists():
        return {"done": {}, "failed": {}}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            obj.setdefault("done", {})
            obj.setdefault("failed", {})
            return obj
    except Exception:
        pass
    return {"done": {}, "failed": {}}


def _save_state(path: str, state: dict[str, object]) -> None:
    p = pathlib.Path(path)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="", help="Path to TSV: <title>\\t<public_url> (optional if --public-url is used)")
    ap.add_argument("--public-url", default="", help="Yandex Disk public folder URL (no manifest mode)")
    ap.add_argument("--state", default=".yadisk_public_to_s3.state.json", help="Resume state file")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="Upload even if object exists")
    ap.add_argument("--key-style", choices=["canonical", "legacy"], default="legacy")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--exclude", action="append", default=[], help="Exclude module folder names (repeatable)")
    args = ap.parse_args()

    public_url = str(args.public_url or "").strip()
    manifest = str(args.manifest or "").strip()

    items: list[Item] = []
    if public_url:
        root_dirs = _yadisk_list_root_dirs(public_url=public_url, limit=int(args.limit or 200))
        excludes = {str(x).strip() for x in (args.exclude or []) if str(x).strip()}
        for d in root_dirs:
            title = str(d.get("name") or "").strip() or "module"
            if title in excludes:
                continue
            path = str(d.get("path") or "").strip()
            if not path:
                continue
            items.append(Item(title=title, url=path))
    elif manifest:
        items = _read_manifest(manifest)
    else:
        raise SystemExit("Provide --public-url or --manifest")

    state = _load_state(str(args.state))

    done: dict[str, object] = state.get("done") if isinstance(state.get("done"), dict) else {}
    failed: dict[str, object] = state.get("failed") if isinstance(state.get("failed"), dict) else {}

    total = len(items)
    uploaded = 0
    skipped = 0
    errors = 0

    for idx, it in enumerate(items, start=1):
        if str(args.key_style).strip().lower() == "canonical":
            key = _canonical_upload_key(it.title)
        else:
            key = _legacy_upload_key(it.title)

        if str(key) in done and not args.force:
            skipped += 1
            continue

        exists = _s3_object_exists(key=key)
        if exists and not args.force:
            done[str(key)] = {"title": it.title, "url": it.url, "status": "exists", "at": datetime.utcnow().isoformat()}
            _save_state(str(args.state), {"done": done, "failed": failed})
            skipped += 1
            continue

        if args.dry_run:
            print(f"DRY\t{idx}/{total}\t{it.title}\t{key}\t{it.url}")
            skipped += 1
            continue

        last_err: str | None = None
        for attempt in range(1, int(args.retries) + 1):
            try:
                print(f"GET\t{idx}/{total}\tattempt={attempt}\t{it.title}\t{key}")
                url = str(it.url or "").strip()
                if public_url and (not url.lower().startswith("http")):
                    href = _yadisk_get_download_href(public_url=public_url, path=url)
                    if not href:
                        raise RuntimeError("failed to get download href")
                    url = href

                data_iter = _iter_bytes_from_url(url=url, timeout=float(args.timeout))
                size, sha256 = _upload_stream_to_s3(key=key, it=data_iter)

                done[str(key)] = {
                    "title": it.title,
                    "url": it.url,
                    "status": "uploaded",
                    "bytes": int(size),
                    "sha256": sha256,
                    "at": datetime.utcnow().isoformat(),
                }
                if str(key) in failed:
                    failed.pop(str(key), None)

                _save_state(str(args.state), {"done": done, "failed": failed})
                uploaded += 1
                last_err = None
                break
            except Exception as e:
                last_err = f"{type(e).__name__}: {str(e)}"
                time.sleep(float(args.sleep))

        if last_err:
            failed[str(key)] = {"title": it.title, "url": it.url, "error": last_err, "at": datetime.utcnow().isoformat()}
            _save_state(str(args.state), {"done": done, "failed": failed})
            errors += 1

    print(f"total={total}")
    print(f"uploaded={uploaded}")
    print(f"skipped={skipped}")
    print(f"errors={errors}")
    print(f"bucket={settings.s3_bucket}")

    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
