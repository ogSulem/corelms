from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.core.security import get_current_user
from app.services.storage import get_s3_client

router = APIRouter(prefix="/quickstart", tags=["quickstart"])


def _body_iter(body):
    while True:
        chunk = body.read(1024 * 1024)
        if not chunk:
            break
        yield chunk


@router.get("/stream")
def stream_quickstart(
    request: Request,
    _: object = Depends(get_current_user),
    range_header: str | None = Header(default=None, alias="Range"),
    __: object = rate_limit(key_prefix="quickstart_stream", limit=240, window_seconds=60),
):
    object_key = str(getattr(settings, "quickstart_object_key", "") or "").strip()
    if not object_key:
        raise HTTPException(status_code=404, detail="not found")

    filename = object_key.split("/")[-1] or "quickstart"
    quoted = urllib.parse.quote(filename, safe="")
    disposition = f"inline; filename*=UTF-8''{quoted}"

    range_value = str(range_header or "").strip()
    range_value_l = range_value.lower()

    start: int | None = None
    end: int | None = None
    suffix_len: int | None = None

    if range_value_l.startswith("bytes="):
        try:
            spec = range_value_l.split("=", 1)[1]
            part = spec.split(",", 1)[0].strip()
            a, b = part.split("-", 1)
            a = a.strip()
            b = b.strip()
            if a and a.isdigit():
                start = int(a)
            if b and b.isdigit():
                end = int(b)
            if (not a) and b and b.isdigit():
                suffix_len = int(b)
        except Exception:
            start = None
            end = None
            suffix_len = None

    s3 = get_s3_client()
    size_total = None
    try:
        head = s3.head_object(Bucket=settings.s3_bucket, Key=object_key)
        size_total = int(head.get("ContentLength") or 0)
    except Exception:
        size_total = None

    kwargs: dict[str, object] = {"Bucket": settings.s3_bucket, "Key": object_key}

    if range_value_l.startswith("bytes=") and size_total is not None:
        invalid = False

        if suffix_len is not None:
            if suffix_len <= 0:
                invalid = True
            else:
                if suffix_len >= size_total:
                    start = 0
                else:
                    start = max(0, size_total - suffix_len)
                end = size_total - 1

        if start is not None:
            if start < 0 or start >= size_total:
                invalid = True

        if end is not None:
            if end < 0 or end >= size_total:
                invalid = True

        if start is not None and end is not None and start > end:
            invalid = True

        if invalid:
            headers = {"Accept-Ranges": "bytes", "Content-Range": f"bytes */{int(size_total)}"}
            raise HTTPException(status_code=416, detail="invalid range", headers=headers)

        if start is not None and end is None:
            kwargs["Range"] = f"bytes={start}-"
        elif start is not None and end is not None:
            kwargs["Range"] = f"bytes={start}-{end}"

    try:
        obj = s3.get_object(**kwargs)
        body = obj.get("Body")
        if body is None:
            raise HTTPException(status_code=404, detail="not found")

        content_type = str(getattr(settings, "quickstart_mime_type", "") or "").strip() or str(obj.get("ContentType") or "video/mp4")

        headers = {
            "Content-Disposition": disposition,
            "Accept-Ranges": "bytes",
        }
        if obj.get("ContentRange"):
            headers["Content-Range"] = str(obj.get("ContentRange"))

        status_code = 206 if ("Range" in kwargs) else 200
        return StreamingResponse(
            _body_iter(body),
            media_type=content_type,
            status_code=status_code,
            headers=headers,
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
