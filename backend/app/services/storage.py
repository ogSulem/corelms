from __future__ import annotations

import boto3
from botocore.client import Config

from app.core.config import settings


def get_s3_client(*, endpoint_url: str | None = None):
    ep = (endpoint_url or "").strip() or None
    # For AWS S3, endpoint_url must be None.
    # For S3-compatible providers (MinIO/R2/YC), endpoint_url is required.
    return boto3.client(
        "s3",
        endpoint_url=ep or (str(getattr(settings, "s3_endpoint_url", "") or "").strip() or None),
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region_name,
        config=Config(
            signature_version="s3v4",
            connect_timeout=float(getattr(settings, "s3_connect_timeout_seconds", 3.0)),
            read_timeout=float(getattr(settings, "s3_read_timeout_seconds", 60.0)),
            retries={
                "max_attempts": int(getattr(settings, "s3_max_attempts", 5)),
                "mode": "standard",
            },
            max_pool_connections=int(getattr(settings, "s3_max_pool_connections", 50)),
            s3={
                "addressing_style": str(getattr(settings, "s3_addressing_style", "path")),
            },
        ),
    )


def _get_presign_client():
    pub = (settings.s3_public_endpoint_url or "").strip()
    # Presign client does not contact S3; endpoint_url affects only the signed host.
    return get_s3_client(endpoint_url=pub or settings.s3_endpoint_url)


def ensure_bucket_exists() -> None:
    s3 = get_s3_client()
    try:
        s3.head_bucket(Bucket=settings.s3_bucket)
    except Exception:
        env = (getattr(settings, "app_env", "") or "").strip().lower()
        # In production we should NOT auto-create buckets.
        # This prevents accidental bucket creation under wrong account/region.
        if env in {"prod", "production"}:
            raise

        # Dev convenience: auto-create bucket.
        # AWS requires LocationConstraint for non-us-east-1.
        region = str(getattr(settings, "s3_region_name", "") or "").strip() or "us-east-1"
        ep = str(getattr(settings, "s3_endpoint_url", "") or "").strip()
        is_aws = not ep
        if is_aws and region not in {"us-east-1", ""}:
            s3.create_bucket(
                Bucket=settings.s3_bucket,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        else:
            s3.create_bucket(Bucket=settings.s3_bucket)


def presign_put(*, object_key: str, content_type: str | None, expires_seconds: int = 900) -> str:
    ensure_bucket_exists()
    s3 = _get_presign_client()
    params: dict[str, object] = {"Bucket": settings.s3_bucket, "Key": object_key}
    if content_type:
        params["ContentType"] = content_type

    return s3.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=expires_seconds,
    )


def presign_get(*, object_key: str, expires_seconds: int = 900) -> str:
    ensure_bucket_exists()
    s3 = _get_presign_client()
    try:
        cfg = int(getattr(settings, "s3_presign_download_expires_seconds", 0) or 0)
        if cfg > 0:
            expires_seconds = cfg
        if (getattr(settings, "app_env", "") or "").strip().lower() in {"prod", "production"}:
            expires_seconds = max(60, min(int(expires_seconds), 300))
    except Exception:
        pass
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": object_key},
        ExpiresIn=expires_seconds,
    )
