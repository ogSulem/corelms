from __future__ import annotations

import json
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.core.security import get_current_user, require_roles
from app.models.user import User, UserRole
from app.services.storage import (
    get_s3_client,
    presign_get,
    presign_put,
    s3_invalidate_common_prefixes,
    s3_invalidate_prefix_has_objects,
)


router = APIRouter(prefix="/sales-files", tags=["sales"])


Section = Literal["photos", "catalogs"]


def _section_prefix(section: str) -> str:
    s = str(section or "").strip().lower()
    if s not in {"photos", "catalogs"}:
        raise HTTPException(status_code=400, detail="invalid section")
    return f"sales/{s}"


def _normalize_path(path: str | None) -> str:
    p = str(path or "").strip().replace("\\", "/")
    p = p.strip("/")
    if not p:
        return ""
    # avoid directory traversal patterns
    parts = [x for x in p.split("/") if x and x not in {".", ".."}]
    return "/".join(parts)


def _join_key(prefix: str, path: str, filename: str | None = None) -> str:
    p = str(prefix or "").strip().strip("/")
    pp = _normalize_path(path)
    if filename is None:
        return f"{p}/{pp}".rstrip("/")
    fn = str(filename or "").strip().replace("\\", "/")
    fn = fn.split("/")[-1].strip()
    if not fn:
        raise HTTPException(status_code=400, detail="missing filename")
    if pp:
        return f"{p}/{pp}/{fn}"
    return f"{p}/{fn}"


class PresignUploadRequest(BaseModel):
    section: Section
    path: str | None = None
    filename: str
    content_type: str | None = None


class PresignUploadResponse(BaseModel):
    key: str
    upload_url: str


class PresignDownloadResponse(BaseModel):
    url: str


class ListEntry(BaseModel):
    kind: Literal["folder", "file"]
    title: str
    key: str
    size: int | None = None
    last_modified: str | None = None


class ListResponse(BaseModel):
    prefix: str
    path: str
    entries: list[ListEntry]


class MkdirRequest(BaseModel):
    section: Section
    path: str | None = None
    name: str


class DeleteObjectRequest(BaseModel):
    key: str


class DeleteFolderRequest(BaseModel):
    section: Section
    path: str | None = None


@router.get("/list", response_model=ListResponse)
def list_sales_files(
    section: Section,
    path: str | None = Query(default=None),
    _: User = Depends(get_current_user),
    __: object = rate_limit(key_prefix="sales_files_list", limit=240, window_seconds=60),
):
    base = _section_prefix(section)
    rel = _normalize_path(path)
    prefix = _join_key(base, rel)
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"

    s3 = get_s3_client()

    # S3 folders are prefixes; list direct children via Delimiter
    token: str | None = None
    folders: set[str] = set()
    files: list[dict[str, object]] = []
    while True:
        kwargs: dict[str, object] = {
            "Bucket": settings.s3_bucket,
            "Prefix": prefix,
            "Delimiter": "/",
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)

        for cp in (resp.get("CommonPrefixes") or []):
            try:
                pfx = str((cp or {}).get("Prefix") or "")
                if not pfx:
                    continue
                folders.add(pfx)
            except Exception:
                continue

        for it in (resp.get("Contents") or []):
            try:
                key = str((it or {}).get("Key") or "")
                if not key:
                    continue
                # Skip folder marker objects
                if key.endswith("/.keep") or key.endswith("/"):
                    continue
                # Do not include the prefix object itself
                if key == prefix:
                    continue
                files.append(it)
            except Exception:
                continue

        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
        if not token:
            break

    entries: list[ListEntry] = []

    # Folders
    for f in sorted(folders):
        # f is full prefix, e.g. sales/photos/a/b/
        name = f[len(prefix) :].rstrip("/")
        name = name.split("/")[0] if "/" in name else name
        if not name:
            continue
        entries.append(ListEntry(kind="folder", title=name, key=f))

    # Files
    def _basename(k: str) -> str:
        kk = k.rstrip("/")
        return kk.split("/")[-1] if "/" in kk else kk

    for it in files:
        key = str((it or {}).get("Key") or "")
        if not key or not key.startswith(prefix):
            continue
        tail = key[len(prefix) :]
        if not tail or "/" in tail:
            # should not happen with Delimiter, but keep hardening
            continue
        lm = None
        try:
            lm = (it or {}).get("LastModified")
            lm = lm.isoformat() if lm else None
        except Exception:
            lm = None
        try:
            size = int((it or {}).get("Size") or 0)
        except Exception:
            size = 0
        entries.append(ListEntry(kind="file", title=_basename(key), key=key, size=size, last_modified=lm))

    # folders first, then files
    entries.sort(key=lambda e: (0 if e.kind == "folder" else 1, e.title.lower()))

    return ListResponse(prefix=base, path=rel, entries=entries)


@router.get("/presign-download", response_model=PresignDownloadResponse)
def presign_sales_download(
    key: str,
    _: User = Depends(get_current_user),
    __: object = rate_limit(key_prefix="sales_files_presign_get", limit=600, window_seconds=60),
):
    k = str(key or "").strip().lstrip("/")
    if not k.startswith("sales/photos/") and not k.startswith("sales/catalogs/"):
        raise HTTPException(status_code=400, detail="invalid key")
    url = presign_get(object_key=k)
    return PresignDownloadResponse(url=url)


@router.post("/presign-upload", response_model=PresignUploadResponse)
def presign_sales_upload(
    request: Request,
    body: PresignUploadRequest,
    user: User = Depends(require_roles(UserRole.superadmin)),
    _: object = rate_limit(key_prefix="sales_files_presign_put", limit=60, window_seconds=60),
):
    base = _section_prefix(body.section)
    rel = _normalize_path(body.path)
    object_key = _join_key(base, rel, body.filename)

    ct = str(body.content_type or "").strip() or "application/octet-stream"

    # Best-effort hardening: prevent overwriting by default.
    # If you want overwrite, we can add an explicit flag.
    s3 = get_s3_client()
    try:
        s3.head_object(Bucket=settings.s3_bucket, Key=object_key)
        raise HTTPException(status_code=409, detail="object already exists")
    except HTTPException:
        raise
    except Exception:
        pass

    upload_url = presign_put(object_key=object_key, content_type=ct)

    # Invalidate folder listings caches (if any)
    try:
        s3_invalidate_common_prefixes(prefix=f"{base}/{rel}")
        s3_invalidate_prefix_has_objects(prefix=f"{base}/{rel}")
    except Exception:
        pass

    return PresignUploadResponse(key=object_key, upload_url=upload_url)


@router.post("/mkdir")
def mkdir_sales_folder(
    body: MkdirRequest,
    user: User = Depends(require_roles(UserRole.superadmin)),
    _: object = rate_limit(key_prefix="sales_files_mkdir", limit=60, window_seconds=60),
):
    base = _section_prefix(body.section)
    rel = _normalize_path(body.path)
    name = str(body.name or "").strip().replace("\\", "/").strip("/")
    name = name.split("/")[0].strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing folder name")
    if name in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid folder name")

    folder_prefix = _join_key(base, os.path.join(rel, name).replace("\\", "/"))
    marker_key = folder_prefix.rstrip("/") + "/.keep"

    s3 = get_s3_client()
    s3.put_object(Bucket=settings.s3_bucket, Key=marker_key, Body=b"", ContentType="application/octet-stream")

    try:
        s3_invalidate_common_prefixes(prefix=f"{base}/{rel}")
        s3_invalidate_prefix_has_objects(prefix=f"{base}/{rel}")
    except Exception:
        pass

    return {"ok": True, "key": marker_key}


@router.delete("/object")
def delete_sales_object(
    key: str,
    user: User = Depends(require_roles(UserRole.superadmin)),
    _: object = rate_limit(key_prefix="sales_files_delete_object", limit=240, window_seconds=60),
):
    k = str(key or "").strip().lstrip("/")
    if not k.startswith("sales/photos/") and not k.startswith("sales/catalogs/"):
        raise HTTPException(status_code=400, detail="invalid key")

    s3 = get_s3_client()
    s3.delete_object(Bucket=settings.s3_bucket, Key=k)

    # invalidate parent listing cache (best-effort)
    try:
        parent = k.rsplit("/", 1)[0]
        s3_invalidate_common_prefixes(prefix=parent)
        s3_invalidate_prefix_has_objects(prefix=parent)
    except Exception:
        pass

    return {"ok": True}


@router.delete("/folder")
def delete_sales_folder(
    section: Section,
    path: str | None = Query(default=None),
    user: User = Depends(require_roles(UserRole.superadmin)),
    _: object = rate_limit(key_prefix="sales_files_delete_folder", limit=60, window_seconds=60),
):
    base = _section_prefix(section)
    rel = _normalize_path(path)
    prefix = _join_key(base, rel)
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"

    s3 = get_s3_client()

    # Delete all objects under prefix in batches.
    token: str | None = None
    keys: list[str] = []
    while True:
        kwargs: dict[str, object] = {"Bucket": settings.s3_bucket, "Prefix": prefix, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        for it in (resp.get("Contents") or []):
            try:
                k = str((it or {}).get("Key") or "")
                if k:
                    keys.append(k)
            except Exception:
                continue
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
        if not token:
            break

    for i in range(0, len(keys), 1000):
        chunk = keys[i : i + 1000]
        if not chunk:
            continue
        s3.delete_objects(
            Bucket=settings.s3_bucket,
            Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True},
        )

    try:
        parent = prefix.rstrip("/").rsplit("/", 1)[0]
        s3_invalidate_common_prefixes(prefix=parent)
        s3_invalidate_prefix_has_objects(prefix=parent)
    except Exception:
        pass

    return {"ok": True, "deleted": len(keys)}
