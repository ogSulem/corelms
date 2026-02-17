from __future__ import annotations

from pydantic import BaseModel


class AssetCreateRequest(BaseModel):
    object_key: str
    original_filename: str
    mime_type: str | None = None


class AssetCreateResponse(BaseModel):
    asset_id: str
    upload_url: str


class AssetGetUrlResponse(BaseModel):
    asset_id: str
    download_url: str
